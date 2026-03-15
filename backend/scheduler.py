"""PP1 Scheduler — backward scheduling with factory rules.

Rules from Francisco (Incompol):
1. Produce 1-2 days before delivery date (backward scheduling)
2. Respect economic lot minimums
3. Twin parts / shared material → same machine
4. Alerts: red=tomorrow, yellow=2 days, priority #1=atraso (negative)
"""

import json
from datetime import datetime, timedelta

from models import Alert, Constraint, Machine, Reference, ScheduledJob

# Working hours config
SHIFT_START_HOUR = 6
HOURS_PER_DAY = 16  # 2 shifts: 06:00–22:00
BUFFER_DAYS = 2  # Produce 1-2 days before need date


class Scheduler:
    def __init__(
        self,
        references: list[Reference],
        machines: list[Machine],
        constraints: list[Constraint] = None,
        today: str = None,
    ):
        self.references = {f"{r.ref_id}_{r.client_code}": r for r in references}
        self.machines = {m.machine_id: m for m in machines}
        self.constraints = constraints or []
        self.today = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now()
        self.schedule: list[ScheduledJob] = []
        self.alerts: list[Alert] = []
        self._job_counter = 0

        # Machine timeline: {machine_id: [(start, end, job_id), ...]}
        self.machine_timeline: dict[str, list] = {m: [] for m in self.machines}

        # Custom overrides from LLM
        self.lot_overrides: dict[str, int] = {}
        self.machine_overrides: dict[str, str] = {}
        self.affinity_groups: list[dict] = []
        self.buffer_override: int = BUFFER_DAYS

    def _next_job_id(self) -> str:
        self._job_counter += 1
        return f"JOB-{self._job_counter:04d}"

    def _production_hours(self, quantity: int, pieces_per_hour: int) -> float:
        """Hours needed to produce quantity."""
        if pieces_per_hour <= 0:
            return 1.0  # Default 1 hour for unknowns
        return quantity / pieces_per_hour

    def _find_slot(
        self, machine_id: str, hours_needed: float, deadline: datetime
    ) -> tuple[datetime, datetime]:
        """Find the latest slot before deadline on this machine (backward scheduling)."""
        # Target: finish production BUFFER days before deadline
        target_end = deadline - timedelta(days=self.buffer_override)

        # Don't schedule in the past
        min_start = self.today + timedelta(hours=SHIFT_START_HOUR - self.today.hour)
        if min_start < self.today:
            min_start = self.today + timedelta(days=1)
            min_start = min_start.replace(hour=SHIFT_START_HOUR, minute=0, second=0)

        # Calculate start time from target end
        days_needed = hours_needed / HOURS_PER_DAY
        full_days = int(days_needed)
        remaining_hours = hours_needed - (full_days * HOURS_PER_DAY)

        proposed_start = target_end - timedelta(days=full_days, hours=remaining_hours)

        # Clamp to min_start
        if proposed_start < min_start:
            proposed_start = min_start

        proposed_end = proposed_start + timedelta(hours=hours_needed)

        # Check for conflicts on this machine
        timeline = sorted(self.machine_timeline[machine_id], key=lambda x: x[0])

        # Try to fit in the timeline
        for existing_start, existing_end, _ in timeline:
            if proposed_start < existing_end and proposed_end > existing_start:
                # Conflict — shift earlier
                proposed_end = existing_start
                proposed_start = proposed_end - timedelta(hours=hours_needed)
                if proposed_start < min_start:
                    # Can't fit before, try after
                    proposed_start = existing_end
                    proposed_end = proposed_start + timedelta(hours=hours_needed)

        return proposed_start, proposed_end

    def _get_effective_lot(self, ref: Reference) -> int:
        """Get effective lot size considering overrides."""
        key = f"{ref.ref_id}_{ref.client_code}"
        if key in self.lot_overrides:
            return self.lot_overrides[key]
        if ref.ref_id in self.lot_overrides:
            return self.lot_overrides[ref.ref_id]
        return ref.economic_lot

    def _get_effective_machine(self, ref: Reference) -> str:
        """Get effective machine considering overrides and affinity."""
        key = f"{ref.ref_id}_{ref.client_code}"
        if key in self.machine_overrides:
            return self.machine_overrides[key]
        if ref.ref_id in self.machine_overrides:
            return self.machine_overrides[ref.ref_id]

        # Check affinity groups
        for group in self.affinity_groups:
            if ref.ref_id in group.get("refs", []):
                return group.get("machine", ref.machine)

        return ref.machine

    def _calculate_priority(self, ref: Reference) -> int:
        """0=normal, 1=yellow (within 5 days), 2=red (within 2 days), 3=atraso (already late or today)."""
        today_str = self.today.strftime("%Y-%m-%d")
        in_2_days = (self.today + timedelta(days=2)).strftime("%Y-%m-%d")
        in_5_days = (self.today + timedelta(days=5)).strftime("%Y-%m-%d")

        shortage_date = ref.first_shortage_date
        if not shortage_date:
            return 0  # No shortage, all good

        # ATRASO: shortage date is today or in the past
        if shortage_date <= today_str:
            return 3

        # RED: shortage within 2 days
        if shortage_date <= in_2_days:
            return 2

        # YELLOW: shortage within 5 days
        if shortage_date <= in_5_days:
            return 1

        return 0

    def schedule_all(self) -> dict:
        """Run the scheduler. Returns summary."""
        self.schedule = []
        self.alerts = []
        self._job_counter = 0
        self.machine_timeline = {m: [] for m in self.machines}

        # Collect all jobs to schedule
        jobs_to_schedule = []
        for key, ref in self.references.items():
            if not ref.first_shortage_date:
                continue  # No need to produce — sufficient stock

            priority = self._calculate_priority(ref)
            shortage_date = ref.first_shortage_date
            machine = self._get_effective_machine(ref)
            lot = self._get_effective_lot(ref)

            # Calculate quantity: at least economic lot, at least what's needed
            # The shortage value tells us how much we need
            first_shortage_val = abs(ref.daily_coverage.get(shortage_date, 0))
            quantity = max(lot, first_shortage_val) if lot > 0 else first_shortage_val

            # Minimum: at least the shortage
            if quantity < first_shortage_val:
                quantity = first_shortage_val

            jobs_to_schedule.append(
                {
                    "key": key,
                    "ref": ref,
                    "priority": priority,
                    "shortage_date": shortage_date,
                    "machine": machine,
                    "quantity": quantity,
                    "lot": lot,
                }
            )

        # Sort: highest priority first, then earliest shortage
        jobs_to_schedule.sort(key=lambda j: (-j["priority"], j["shortage_date"]))

        # Schedule each job
        for job_info in jobs_to_schedule:
            ref = job_info["ref"]
            machine_id = job_info["machine"]
            quantity = job_info["quantity"]
            priority = job_info["priority"]
            shortage_date = datetime.strptime(job_info["shortage_date"], "%Y-%m-%d")

            if machine_id not in self.machines:
                continue

            hours = self._production_hours(quantity, ref.pieces_per_hour)
            start, end = self._find_slot(machine_id, hours, shortage_date)

            job = ScheduledJob(
                job_id=self._next_job_id(),
                ref_id=ref.ref_id,
                machine=machine_id,
                quantity=quantity,
                start_time=start,
                end_time=end,
                pieces_per_hour=ref.pieces_per_hour,
                client_name=ref.client_name,
                designation=ref.designation,
                priority=priority,
                tool=ref.tool,
            )
            self.schedule.append(job)
            self.machine_timeline[machine_id].append((start, end, job.job_id))

        # Generate alerts
        self._generate_alerts()

        return self._summary()

    def _generate_alerts(self):
        """Generate alerts based on Francisco's rules:
        - Atraso: already late (shortage today or past)
        - Red: shortage within 2 days
        - Yellow: shortage within 5 days
        """
        self.alerts = []
        today_str = self.today.strftime("%Y-%m-%d")

        alert_counter = 0
        for key, ref in self.references.items():
            priority = self._calculate_priority(ref)
            if priority == 0:
                continue

            shortage_date = ref.first_shortage_date
            if not shortage_date:
                continue

            shortage_val = abs(ref.daily_coverage.get(shortage_date, 0))

            if priority == 3:
                severity = "atraso"
                msg = f"ATRASO: {ref.ref_id} ({ref.client_name}) — faltam {shortage_val:,} peças. Prioridade máxima."
            elif priority == 2:
                severity = "red"
                msg = f"URGENTE: {ref.ref_id} ({ref.client_name}) — faltam {shortage_val:,} peças até {shortage_date}."
            elif priority == 1:
                severity = "yellow"
                msg = f"ATENÇÃO: {ref.ref_id} ({ref.client_name}) — faltam {shortage_val:,} peças até {shortage_date}."
            else:
                continue

            alert_counter += 1
            self.alerts.append(
                Alert(
                    alert_id=f"ALT-{alert_counter:04d}",
                    ref_id=ref.ref_id,
                    client_name=ref.client_name,
                    designation=ref.designation,
                    severity=severity,
                    message=msg,
                    shortage_qty=shortage_val,
                    machine=ref.machine,
                    due_date=shortage_date,
                )
            )

        # Sort alerts: atraso first, then red, then yellow
        severity_order = {"atraso": 0, "red": 1, "yellow": 2, "info": 3}
        self.alerts.sort(key=lambda a: (severity_order.get(a.severity, 9), a.due_date))

    def _summary(self) -> dict:
        """Summary of scheduling results."""
        jobs_by_machine = {}
        for job in self.schedule:
            if job.machine not in jobs_by_machine:
                jobs_by_machine[job.machine] = []
            jobs_by_machine[job.machine].append(job)

        alerts_by_severity = {}
        for alert in self.alerts:
            if alert.severity not in alerts_by_severity:
                alerts_by_severity[alert.severity] = 0
            alerts_by_severity[alert.severity] += 1

        return {
            "total_jobs": len(self.schedule),
            "jobs_by_machine": {m: len(jobs) for m, jobs in jobs_by_machine.items()},
            "total_alerts": len(self.alerts),
            "alerts_by_severity": alerts_by_severity,
            "schedule_horizon": f"{self.today.strftime('%Y-%m-%d')} to {(self.today + timedelta(days=60)).strftime('%Y-%m-%d')}",
        }

    def get_schedule_json(self) -> list[dict]:
        """Get schedule as JSON-serializable list."""
        return [
            {
                "job_id": j.job_id,
                "ref_id": j.ref_id,
                "machine": j.machine,
                "quantity": j.quantity,
                "start": j.start_time.isoformat(),
                "end": j.end_time.isoformat(),
                "duration_hours": round((j.end_time - j.start_time).total_seconds() / 3600, 1),
                "client": j.client_name,
                "designation": j.designation,
                "priority": j.priority,
                "tool": j.tool,
                "pieces_per_hour": j.pieces_per_hour,
            }
            for j in self.schedule
        ]

    def get_alerts_json(self) -> list[dict]:
        """Get alerts as JSON-serializable list."""
        return [
            {
                "alert_id": a.alert_id,
                "ref_id": a.ref_id,
                "client": a.client_name,
                "designation": a.designation,
                "severity": a.severity,
                "message": a.message,
                "shortage_qty": a.shortage_qty,
                "machine": a.machine,
                "due_date": a.due_date,
            }
            for a in self.alerts
        ]

    def get_references_json(self) -> list[dict]:
        """Get all references as JSON."""
        result = []
        for key, ref in self.references.items():
            result.append(
                {
                    "key": key,
                    "ref_id": ref.ref_id,
                    "client_code": ref.client_code,
                    "client_name": ref.client_name,
                    "designation": ref.designation,
                    "economic_lot": ref.economic_lot,
                    "lead_time_days": ref.lead_time_days,
                    "machine": ref.machine,
                    "tool": ref.tool,
                    "pieces_per_hour": ref.pieces_per_hour,
                    "stock": ref.stock,
                    "twin_ref": ref.twin_ref,
                    "first_shortage": ref.first_shortage_date,
                    "priority": self._calculate_priority(ref),
                }
            )
        return sorted(result, key=lambda r: (-(r["priority"]), r.get("first_shortage") or "9999"))

    # === LLM TOOL FUNCTIONS ===

    def add_machine(self, machine_id: str, shifts: list = None) -> str:
        """Add a new machine."""
        if machine_id in self.machines:
            return f"Máquina {machine_id} já existe."
        self.machines[machine_id] = Machine(
            machine_id=machine_id, shifts=shifts or ["manha", "tarde"]
        )
        self.machine_timeline[machine_id] = []
        return f"Máquina {machine_id} adicionada com turnos {shifts or ['manha', 'tarde']}."

    def set_economic_lot(self, ref_id: str, quantity: int) -> str:
        """Override economic lot for a reference."""
        self.lot_overrides[ref_id] = quantity
        return f"Lote económico da ref {ref_id} alterado para {quantity} peças."

    def add_material_affinity(self, refs: list[str], machine: str, reason: str = "") -> str:
        """Group references that share raw material → same machine."""
        self.affinity_groups.append(
            {
                "refs": refs,
                "machine": machine,
                "reason": reason,
            }
        )
        return f"Refs {', '.join(refs)} agrupadas na máquina {machine}. Razão: {reason}"

    def set_machine_override(self, ref_id: str, machine: str) -> str:
        """Override machine assignment for a reference."""
        if machine not in self.machines:
            return (
                f"Máquina {machine} não existe. Máquinas disponíveis: {list(self.machines.keys())}"
            )
        self.machine_overrides[ref_id] = machine
        return f"Ref {ref_id} reassignada à máquina {machine}."

    def set_buffer_days(self, days: int) -> str:
        """Change the production buffer (days before delivery)."""
        self.buffer_override = days
        return f"Buffer de produção alterado para {days} dias antes da entrega."

    def remove_machine(self, machine_id: str) -> str:
        """Remove a machine (mark unavailable)."""
        if machine_id in self.machines:
            self.machines[machine_id].available = False
            return f"Máquina {machine_id} marcada como indisponível."
        return f"Máquina {machine_id} não encontrada."

    def explain_ref(self, ref_id: str) -> str:
        """Get detailed info about a reference for LLM to explain."""
        matches = [(k, r) for k, r in self.references.items() if r.ref_id == ref_id]
        if not matches:
            return f"Referência {ref_id} não encontrada."

        explanations = []
        for key, ref in matches:
            shortage = ref.first_shortage_date
            priority = self._calculate_priority(ref)
            priority_label = {
                0: "Normal",
                1: "Atenção (2 dias)",
                2: "Urgente (amanhã)",
                3: "ATRASO",
            }

            # Find scheduled job
            scheduled = [j for j in self.schedule if j.ref_id == ref_id]

            info = {
                "ref": ref.ref_id,
                "client": f"{ref.client_name} ({ref.client_code})",
                "designation": ref.designation,
                "machine": ref.machine,
                "tool": ref.tool,
                "stock_actual": ref.stock,
                "economic_lot": ref.economic_lot,
                "pieces_per_hour": ref.pieces_per_hour,
                "twin_ref": ref.twin_ref,
                "first_shortage": shortage,
                "priority": priority_label.get(priority, "Unknown"),
                "coverage_next_days": {},
            }

            # Coverage for next 7 days
            sorted_dates = sorted(ref.daily_coverage.keys())
            for dt in sorted_dates[:7]:
                info["coverage_next_days"][dt] = ref.daily_coverage[dt]

            if scheduled:
                info["scheduled_jobs"] = [
                    {
                        "job_id": j.job_id,
                        "machine": j.machine,
                        "quantity": j.quantity,
                        "start": j.start_time.strftime("%Y-%m-%d %H:%M"),
                        "end": j.end_time.strftime("%Y-%m-%d %H:%M"),
                    }
                    for j in scheduled
                ]

            explanations.append(info)

        return json.dumps(explanations, indent=2, ensure_ascii=False)

    def get_machine_load(self) -> str:
        """Get machine load summary."""
        result = {}
        for machine_id, timeline in self.machine_timeline.items():
            total_hours = sum((end - start).total_seconds() / 3600 for start, end, _ in timeline)
            capacity = self.machines[machine_id].daily_capacity_hours * 30  # ~30 days
            result[machine_id] = {
                "scheduled_hours": round(total_hours, 1),
                "capacity_hours_30d": round(capacity, 1),
                "utilization_pct": round(total_hours / capacity * 100, 1) if capacity > 0 else 0,
                "num_jobs": len(timeline),
            }
        return json.dumps(result, indent=2, ensure_ascii=False)
