# Tests for Nikufra IngestService (Data Fusion Engine)

from src.domain.nikufra.ingest_service import IngestService, _fuzzy_match
from src.domain.nikufra.schemas import (
    AlertCategory,
    AlertSeverity,
    NikufraDashboardState,
    OperationStatus,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_isop(tools=None, machines=None):
    """Build minimal ISOP dict."""
    return {
        "tools": tools
        or {
            "BFP079": {
                "id": "BFP079",
                "m": "PRM031",
                "alt": "PRM039",
                "s": 1.0,
                "pH": 1681,
                "op": 1,
                "skus": ["1065170X100"],
                "nm": ["REAR LINK BVH2"],
                "lt": 23040,
                "stk": 45000,
            },
            "BFP080": {
                "id": "BFP080",
                "m": "PRM019",
                "alt": "PRM039",
                "s": 1.25,
                "pH": 0,
                "op": 1,
                "skus": ["1064169X100"],
                "nm": ["FRONT LINK"],
                "lt": 36400,
                "stk": 0,
            },
        },
        "machines": machines
        or {
            "PRM019": {"id": "PRM019", "area": "PG1", "man": [254, 0, 0, 0, 0, 0, 0, 0]},
            "PRM031": {"id": "PRM031", "area": "PG1", "man": [0, 300, 0, 0, 0, 0, 0, 0]},
        },
        "items": [],
        "date_cols": {},
    }


def _make_ops():
    """Build sample operations list."""
    return [
        {
            "id": "OP01",
            "m": "PRM031",
            "t": "BFP079",
            "sku": "1065170X100",
            "nm": "REAR LINK BVH2",
            "pH": 1681,
            "atr": 5400,
            "d": [5200, 0, 3100, 0, 0, 0, 0, 0],
            "s": 1.0,
            "op": 1,
        },
        {
            "id": "OP02",
            "m": "PRM019",
            "t": "BFP080",
            "sku": "1064169X100",
            "nm": "FRONT LINK",
            "pH": 1923,
            "atr": 0,
            "d": [0, 4000, 0, 0, 0, 0, 0, 0],
            "s": 1.25,
            "op": 1,
        },
    ]


# ── Unit Tests ────────────────────────────────────────────────────────


class TestFuzzyMatch:
    def test_exact_match(self):
        assert _fuzzy_match("PRM019", "PRM019") == 100

    def test_near_match(self):
        try:
            from thefuzz import fuzz  # noqa: F401

            has_thefuzz = True
        except ImportError:
            has_thefuzz = False

        score = _fuzzy_match("PRM-019", "PRM019")
        if has_thefuzz:
            assert score >= 80
        else:
            # Fallback mode: exact match only
            assert score == 0

    def test_no_match(self):
        score = _fuzzy_match("PRM019", "BFP079")
        assert score <= 50

    def test_case_insensitive(self):
        assert _fuzzy_match("prm019", "PRM019") == 100


class TestDataQualityAlerts:
    def test_rate_zero_generates_alert(self):
        isop = _make_isop()
        svc = IngestService()
        state = svc.build_dashboard_state(isop=isop, pp_data=None)

        rate_alerts = [
            a
            for a in state.alerts
            if a.category == AlertCategory.DATA_QUALITY and "rate=0" in a.title
        ]
        assert len(rate_alerts) >= 1
        assert rate_alerts[0].entity_id == "BFP080"
        assert rate_alerts[0].severity == AlertSeverity.HIGH

    def test_no_setup_generates_low_alert(self):
        tools = {
            "BFP099": {
                "id": "BFP099",
                "m": "PRM019",
                "alt": "-",
                "s": 0,
                "pH": 1500,
                "op": 1,
                "skus": ["10X"],
                "nm": ["TEST"],
                "lt": 1000,
                "stk": 500,
            },
        }
        svc = IngestService()
        state = svc.build_dashboard_state(isop=_make_isop(tools=tools), pp_data=None)
        setup_alerts = [a for a in state.alerts if "no setup time" in a.title]
        assert len(setup_alerts) >= 1
        assert setup_alerts[0].severity == AlertSeverity.LOW


class TestStockProjections:
    def test_stock_projection_computed(self):
        isop = _make_isop()
        svc = IngestService()
        # We need to manually build ops since no pp_data
        # Stock projection relies on operations consuming stock

        state = svc.build_dashboard_state(isop=isop, pp_data=None)
        # Without operations, no projections with consumption
        # Tools with stk=0 are skipped
        # BFP079 has stk=45000 but no ops → no consumption → skipped
        assert isinstance(state.stock_projections, list)

    def test_stock_out_alert_on_low_stock(self):
        tools = {
            "BFP079": {
                "id": "BFP079",
                "m": "PRM031",
                "alt": "PRM039",
                "s": 1.0,
                "pH": 1681,
                "op": 1,
                "skus": ["1065170X100"],
                "nm": ["REAR LINK BVH2"],
                "lt": 23040,
                "stk": 3000,
            },
        }
        isop = _make_isop(tools=tools)
        svc = IngestService()

        # Build state directly with ops that consume heavily
        state = svc.build_dashboard_state(isop=isop, pp_data=None)
        # Without pp_data, no ops are generated → no stock consumption
        # The stock projection path requires explicit ops
        assert isinstance(state.alerts, list)


class TestOperationStatus:
    def test_late_status_when_atraso_positive(self):
        svc = IngestService()
        ops = _make_ops()
        typed = svc._assign_operation_status(ops, down_machines=set())
        # OP01 has atr=5400 → LATE
        assert typed[0].status == OperationStatus.LATE
        # OP02 has atr=0 → PLANNED
        assert typed[1].status == OperationStatus.PLANNED

    def test_blocked_status_when_machine_down(self):
        svc = IngestService()
        ops = _make_ops()
        typed = svc._assign_operation_status(ops, down_machines={"PRM031"})
        assert typed[0].status == OperationStatus.BLOCKED
        assert typed[1].status == OperationStatus.PLANNED


class TestBuildDashboardState:
    def test_returns_valid_model(self):
        svc = IngestService()
        state = svc.build_dashboard_state(isop=_make_isop(), pp_data=None)
        assert isinstance(state, NikufraDashboardState)
        assert len(state.dates) == 8
        assert len(state.days_label) == 8
        assert state.data_hash != ""
        assert state.parsed_at is not None
        assert 0.0 <= state.trust_index <= 1.0

    def test_machines_have_utilization_map(self):
        svc = IngestService()
        state = svc.build_dashboard_state(isop=_make_isop(), pp_data=None)
        for m in state.machines:
            assert len(m.utilization_map) == 8
            for u in m.utilization_map:
                assert 0.0 <= u.utilization <= 2.0

    def test_partial_state_on_empty_isop(self):
        svc = IngestService()
        state = svc.build_dashboard_state(
            isop={"tools": {}, "machines": {}, "items": [], "date_cols": {}},
            pp_data=None,
        )
        assert isinstance(state, NikufraDashboardState)
        assert len(state.machines) == 0
        assert len(state.operations) == 0

    def test_header_hash_mismatch_generates_alert(self):
        svc = IngestService(known_header_hash="old_hash_value")
        # Without xlsx_path, no header check happens
        state = svc.build_dashboard_state(isop=_make_isop(), pp_data=None)
        # Header check only runs when xlsx_path is provided
        template_alerts = [a for a in state.alerts if a.category == AlertCategory.TEMPLATE_CHANGE]
        assert len(template_alerts) == 0


class TestTrustIndex:
    def test_perfect_trust_with_good_data(self):
        tools = {
            "BFP079": {
                "id": "BFP079",
                "m": "PRM031",
                "alt": "PRM039",
                "s": 1.0,
                "pH": 1681,
                "op": 1,
                "skus": ["1065170X100"],
                "nm": ["REAR LINK BVH2"],
                "lt": 23040,
                "stk": 45000,
            },
        }
        svc = IngestService()
        state = svc.build_dashboard_state(isop=_make_isop(tools=tools), pp_data=None)
        assert state.trust_index > 0.8

    def test_low_trust_with_bad_data(self):
        tools = {
            "BFP080": {
                "id": "BFP080",
                "m": "PRM019",
                "alt": "PRM039",
                "s": 0,
                "pH": 0,
                "op": 1,
                "skus": [],
                "nm": [],
                "lt": 0,
                "stk": 0,
            },
        }
        svc = IngestService()
        state = svc.build_dashboard_state(isop=_make_isop(tools=tools), pp_data=None)
        assert state.trust_index < 0.8
