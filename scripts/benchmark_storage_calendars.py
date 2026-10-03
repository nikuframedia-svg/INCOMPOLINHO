"""Run against either isolated source tree, never a live database."""

import argparse
import copy
import json
import math
import statistics
import time
import tracemalloc
from contextlib import closing
from datetime import date, timedelta

from backend.config.types import FactoryConfig
from backend.plans.store import PlansStore
from backend.transform.calendars import apply_calendars
from backend.types import EngineData, MachineInfo


def measure(call, repeat):
    seconds = []
    for _ in range(repeat):
        start = time.perf_counter()
        call()
        seconds.append(time.perf_counter() - start)
    tracemalloc.start()
    try:
        call()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"p50_ms": statistics.median(seconds) * 1000,
            "p95_ms": sorted(seconds)[max(0, math.ceil(.95 * len(seconds)) - 1)] * 1000,
            "peak_mib": peak / 1024**2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--repeat", type=int, default=10)
    args = parser.parse_args()
    with closing(PlansStore(args.database)) as store:
        for name, call in (("list", lambda: store.list(500)),
                           ("startup", getattr(store, "active", store.latest))):
            print(json.dumps({"case": name, **measure(call, args.repeat)}), flush=True)
    data = EngineData(ops=[], machines=[MachineInfo("M1", "Grandes", 1020)],
                      twin_groups=[], client_demands={}, holidays=[], n_days=14,
                      workdays=[(date(2026, 9, 21) + timedelta(days=i)).isoformat() for i in range(14)])
    for count in (20, 100, 400, 1000):
        config = FactoryConfig(machine_unavailability=[
            {"id": str(i), "resource": "M1", "start_at": "2026-09-22T08:00", "end_at": "2026-09-22T09:00"}
            for i in range(count)
        ])
        print(json.dumps({"case": "calendars", "entries": count,
                          **measure(lambda: apply_calendars(copy.deepcopy(data), config), args.repeat)}), flush=True)


if __name__ == "__main__":
    main()
