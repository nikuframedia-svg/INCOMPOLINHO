"""Small workbooks for the isolated real-browser acceptance run."""

from datetime import datetime, timedelta

from tests.test_parser import _make_isop_wb


dates = [datetime(2026, 10, 19) + timedelta(days=i) for i in range(7)]
rows = [
    {"client_id": "AUDIT", "client_name": "AUDIT", "sku": f"AUDIT-SKU-{i}",
     "designation": "Audit", "eco_lot": 0, "machine": machine,
     "tool": f"AUDIT-TOOL-{i}", "pH": 60, "operators": 1,
     "stock_a": 0, "wip": 0, "backlog": 0, "np": [0, 0, 0, 0, -1500, 0, 0]}
    for i, machine in enumerate(("PRM019", "PRM031", "PRM039", "PRM043"))
]
workbook = _make_isop_wb(rows=rows, dates=dates)
workbook.save("/tmp/incompolinho-audit-operators.xlsx")
workbook.close()
