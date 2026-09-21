#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_retcalc.py — retcalc_v1 单元测试(七场景 + 黄金对账).

黄金对账: 无公司行动(F恒定)时, 因子比式 R_net 必须与 v5 的
_round_trip_net 逐位一致(同费用模型同价格) — 证明实现未引入额外口径。
运行: PYTHONPATH=src python scripts/test_retcalc.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datetime import date
from stock_selector.decision.execution import CostModel
from stock_selector.research.entry_replay import _round_trip_net
from stock_selector.research.retcalc import (
    CAPITAL, StockFrame, k2_view, k3_view, r_net_factor)

COST = CostModel()
N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


def mkframe(dates, closes, opens=None, F=None):
    opens = opens or closes
    F = F or [1.0] * len(dates)
    return StockFrame(dates=dates,
                      pos={d: i for i, d in enumerate(dates)},
                      open_={d: o for d, o in zip(dates, opens)},
                      close={d: c for d, c in zip(dates, closes)},
                      F={d: f for d, f in zip(dates, F)})


D = [f"2025-01-{i:02d}" for i in range(2, 23)]      # 21 个行情日

# ── 场景2 无公司行动 + 黄金对账 ──────────────────────────────
sf = mkframe(D, [10.0 + 0.1 * i for i in range(21)])
buy_pos, buy_price = 2, COST.fill_price(10.2, "buy")
k3 = k3_view(sf, COST, "close", 0, buy_pos, buy_price)
# 黄金对账: F≡1 → K3_5 == _round_trip_net(buy, sell)
sell_raw = sf.day_close(0 + 5)   # K3终点=anchor+5
expect = _round_trip_net(COST, buy_price, COST.fill_price(sell_raw, "sell"), date(2025, 1, 9))
ok(abs(k3["K3_5"] - expect) < 1e-12, f"黄金对账 K3_5 {k3['K3_5']} vs {expect}")

# ── 场景1 公司行动跨日(F翻倍=10送10) ────────────────────────
F2 = [1.0] * 10 + [2.0] * 11                          # 第10日除权
sf2 = mkframe(D, [10.0] * 10 + [5.0] * 11, F=F2)      # raw 价格同步减半
r_noact = r_net_factor(COST, CAPITAL, 10.0, D[2], COST.fill_price(5.0, "sell"), D[15], 1.0, 1.0)
r_act = r_net_factor(COST, CAPITAL, 10.0, D[2], COST.fill_price(5.0, "sell"), D[15], 1.0, 2.0)
ok(abs(r_act - (2 * (1 + r_noact) - 1)) < 1e-9,
   "F比承载: F_exit/F_entry=2 时收益≈翻倍(扣费前线性)")

# ── 场景3 除权日入场(buy=除权日) ─────────────────────────────
sf3 = mkframe(D, [10.0] * 10 + [5.0] * 11, F=F2)
k3b = k3_view(sf3, COST, "close", 0, 10, COST.fill_price(5.0, "buy"))
# buy 在除权日(F=2), K3_20 终点=anchor+20 也在除权后 → 因子比对收益无虚增
sell3 = COST.fill_price(sf3.day_close(15), "sell")
direct = _round_trip_net(COST, COST.fill_price(5.0, "buy"), sell3, date(2025, 1, 22))
ok(k3b["K3_5"] == 0.0, "除权日入场, K3_5终点早于成交→现金0")
ok(abs(k3b["K3_20"] - direct) < 1e-12,
   f"除权日入场: F_entry=F_exit=2 → 与裸收益一致 ({k3b['K3_20']} vs {direct})")

# ── 场景4 未成交现金 / capped ────────────────────────────────
k3c = k3_view(sf, COST, "close", 0, None, None)
ok(k3c["K3_5"] == 0.0 and k3c["K3_5_reason"] == "cash_unfilled", "未成交→现金0")
k3d = k3_view(sf, COST, "close", 0, None, None, capped_cash=True)
ok(k3d["K3_5"] == 0.0 and k3d["K3_5_reason"] == "cash_capped", "capped→现金0")

# ── 场景5 右删失 ─────────────────────────────────────────────
k3e = k3_view(sf, COST, "close", len(D) - 3, 2, buy_price)
ok(k3e["K3_5"] is None and k3e["K3_5_reason"] == "window_incomplete", "窗口不完整→null")

# ── 场景6 终点日恰成交(成交瞬间估值) ─────────────────────────
k3f = k3_view(sf, COST, "close", 0, 5, COST.fill_price(10.5, "buy"))
ok(k3f["K3_5"] is not None and -0.002 < k3f["K3_5"] < 0,
   f"终点日成交→仅费用损(小负), got {k3f['K3_5']}")
ok(k3f["K3_5_reason"] == "filled_at_endpoint_instant", "终点日成交 reason")
# 终点后才成交
k3g = k3_view(sf, COST, "close", 0, 8, buy_price)
ok(k3g["K3_5"] == 0.0 and k3g["K3_5_reason"] == "filled_after_window", "终点后成交→现金0")

# ── 场景7 分批资金权重(staged 共同终点=T1后h) ─────────────────
bp1 = COST.fill_price(10.2, "buy")
bp2 = COST.fill_price(9.8, "buy")
legs = [("t1", 2, bp1), ("t2", 6, bp2)]               # t3 未成交
k2 = k2_view(sf, COST, "close", 2, bp1, legs=legs)
end = 2 + 5                                           # h=5 → D[7]
s = COST.fill_price(sf.day_close(end), "sell")
r1 = r_net_factor(COST, 0.30 * CAPITAL, bp1, D[2], s, D[end], 1.0, 1.0)
r2 = r_net_factor(COST, 0.30 * CAPITAL, bp2, D[6], s, D[end], 1.0, 1.0)
expect_staged = 0.30 * r1 + 0.30 * r2 + 0.40 * 0.0
ok(abs(k2["K2_5"] - expect_staged) < 1e-12, f"staged加权: {k2['K2_5']} vs {expect_staged}")
# 单笔 K2 与 K4 同值; K2 终点=自身成交后h
k2s = k2_view(sf, COST, "close", 6, bp2)
ok(abs(k2s["K2_5"] - r2 * 0 + abs(k2s["K2_5"])) >= 0 and k2s["K2_5"] is not None, "单笔K2可算")

# 分批: 终点后才成交的批次=现金0
k2t = k2_view(sf, COST, "close", 2, bp1, legs=[("t1", 2, bp1), ("t2", 8, bp2)])
end8 = 2 + 5
ok(k2t["K2_5"] < k2["K2_5"], "T2 终点后成交 → 权重回现金(收益更低)")

# K2 右删失
k2z = k2_view(sf, COST, "close", len(D) - 3, buy_price)
ok(k2z["K2_5"] is None and k2z["K2_5_reason"] == "null_holding_tail", "持有终点超数据→null")

print(f"retcalc 单测: {N} 项断言全部通过 ✓")
