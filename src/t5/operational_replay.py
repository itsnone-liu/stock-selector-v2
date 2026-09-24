"""G6 物理截断重放（独立实现，不 import 生成路径）。

对单事件前缀，从零状态起按 v1 规则顺序重放：
- raw C1 -> C1（hold 置位）
- hold 且 raw C0 且 dd<=delta_q75 且 dist_to_ref20>=0 -> C1
- 其余透传 raw（C6 语义上立即生效即透传）
只读 <=t 信息（前缀内）。
"""
from __future__ import annotations


def replay_event(prefix, dq, field="drawdown_from_peak_log",
                 q="q75"):
    """prefix: 该事件的行（含 final_candidate_state /
    ev_drawdown_from_peak_log / ev_dist_to_ref20 / delta_day）。
    返回 list[str]（与 prefix 等长的 operational 序列）。"""
    out = []
    hold = False
    for r in prefix.to_dict("records"):
        raw = r["final_candidate_state"]
        if raw == "STATE_UNAVAILABLE":
            out.append(raw)
            hold = False
            continue
        if raw == "C1":
            out.append("C1")
            hold = True
            continue
        dd = r.get("ev_drawdown_from_peak_log")
        d20 = r.get("ev_dist_to_ref20")
        thr = dq.get(str(int(r["delta_day"])), {}).get(q)
        if (hold and raw == "C0" and dd is not None
                and d20 is not None and thr is not None
                and dd <= thr and d20 >= 0):
            out.append("C1")
        else:
            out.append(raw)
            hold = False
    return out
