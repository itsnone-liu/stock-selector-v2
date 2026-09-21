#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_identify_e2e_tamper.py — 端到端未来篡改测试 (2026-09-21 复审要求).

改变突破日之后的行情(价格/开高低/量全篡改), 经 process_episode 重新生成
生命周期衍生字段(prep_days/post_hi/plow)与三时点数据集行,
断言: 突破日时点的全部特征完全不变(标签列允许变——它们本来就是结果)。
"""
import csv
import gzip
import sys
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_identify_features import load_stock, process_episode   # noqa: E402

N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


def load_factor_index():
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        next(f)
        for line in f:
            c, d, uc, hc, Fv = line.split(",")
            F.setdefault(c, {})[d] = float(Fv)
    return F


def feat_cols(row, tag):
    return {k: v for k, v in row.items() if k.startswith(f"{tag}_") or k == "prep_days"}


# 取一段有 shrink+stabilization 的真实段
import duckdb  # noqa: E402
v5f = sorted(ROOT.glob("output/research/lifecycle_v1/entry_replay_v5_full/partitions/*/*.parquet"))
lid, fd = duckdb.connect().execute(f"""
    SELECT lifecycle_id, fill_date_close FROM read_parquet({[str(x) for x in v5f]!r})
    WHERE strategy='wait_support_hold' AND fill_status_close='filled'
    LIMIT 1""").fetchone()
lfiles = sorted(ROOT.glob("output/research/lifecycle_v1/lifecycle_stage4_v1_full/partitions/*/*.parquet"))
code6, bo, t2, ps, t3s, ed, rc, pev = duckdb.connect().execute(f"""
    SELECT code, breakout_day, first_pullback_day, preparation_start,
           reattack_days, end_day, right_censored, pullback_event_ids
    FROM read_parquet({[str(x) for x in lfiles]!r}) WHERE lifecycle_id='{lid}'""").fetchone()
code = ("sh." if str(code6)[0] == "6" else "sz.") + str(code6)
path_row = next(r for r in csv.DictReader(gzip.open(ROOT / "output/research/posneg_v1/path_layer.csv.gz", "rt"))
                if r["lifecycle_id"] == lid)

Fidx = load_factor_index()
cache = load_stock(code, Fidx)
life_row = (code, str(bo)[:10], str(t2)[:10] if t2 else None,
            str(ps)[:10] if ps else None,
            str(t3s).split("|")[0] if t3s else None,
            str(ed)[:10] if ed else None, bool(rc), str(pev) if pev else None)

base = process_episode(lid, path_row, life_row, str(fd)[:10], cache)
ok(base["shrink"] and base["stabilization"], "样本段三时点齐备")

# ── 端到端篡改: 突破日之后全部 bar 改写 ──
dates, u, Fd, nvm, vmd = cache
bp = dates.index(str(bo)[:10])
u2 = dict(u)
for d in dates[bp + 1:]:
    o_, h_, l_, c_, v_ = u[d]
    u2[d] = (o_ * 2.7, h_ * 3.1, l_ * 0.4, c_ * 2.9, v_ * 13.0)
cache2 = (dates, u2, Fd, nvm, vmd)
tam = process_episode(lid, path_row, life_row, str(fd)[:10], cache2)

b1, t1 = base["breakout"], tam["breakout"]
diff = {k: (b1[k], t1[k]) for k in feat_cols(b1, "bo") if b1[k] != t1[k]}
ok(not diff, f"端到端: 突破日后行情全篡改, 突破日特征不变! diff={diff}")
ok(b1["obs_vol_missing"] == t1["obs_vol_missing"], "观察日缺失标记不变")

# 标签(结果列)在篡改下不变是 path 层冻结产物使然——本测试只守护特征
# ── 敏感性对照: 篡改突破日当日前一日, 特征应变化(截断真的含当日) ──
u3 = dict(u)
d_prev = dates[bp - 1]
o_, h_, l_, c_, v_ = u[d_prev]
u3[d_prev] = (o_, h_, l_, c_ * 1.5, v_)
cache3 = (dates, u3, Fd, nvm, vmd)
sen = process_episode(lid, path_row, life_row, str(fd)[:10], cache3)
s1 = sen["breakout"]
diff2 = [k for k in feat_cols(b1, "bo") if b1[k] != s1[k]]
ok(diff2, "前移篡改(观察日前一日)应改变特征(截断边界生效)")

print(f"identify 端到端篡改测试: {N} 项断言全部通过 ✓ (样本 {code} {lid})")
