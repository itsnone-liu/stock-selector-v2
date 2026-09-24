#!/usr/bin/env python3
"""拉取 baostock 证监会行业分类快照（非历史时点数据，重跑覆盖）。"""
import baostock as bs, json
from pathlib import Path
bs.login()
rs = bs.query_stock_industry()
rows = []
while rs.error_code == '0' and rs.next():
    rows.append(rs.get_row_data())
bs.logout()
out = Path(__file__).resolve().parents[1] / "data/t4/sector_map/csrc_industry_snapshot.json"
out.parent.mkdir(parents=True, exist_ok=True)
json.dump(rows, open(out, "w"), ensure_ascii=False)
print(f"saved {len(rows)} rows -> {out}")
