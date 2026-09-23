#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calibrate_h2_blocksize.py — H2 块长经验校准(二十一轮原始记录, 二十二轮入库).

零差合成数据 × 独立种子, 经验第一类错误率(名义 5%)。
注(二十二轮用户裁定): 单样本 p>0.10 判据过严(有效检验零假设下也可能小 p);
20 种子校准仅为初步记录, 40/20 日块均未建立可信推断依据——B 裁决下
H2 不执行任何 bootstrap 推断。本脚本作为独立方法研究课题的种子保存,
不得用于事后选择使 H2 显著的方案。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import condition_h2stats as st  # noqa: E402
from test_condition_h2_synthetic import make_synthetic  # noqa: E402

SEED_BASE = 20260922

def fp_rate(block, n_seeds=20):
    st.BLOCK = block
    n_rej = 0
    detail = []
    for s in range(n_seeds):
        r = st.h2_test(make_synthetic(0.20, 0.20, seed=700 + s), "hi", "lo",
                       seed=SEED_BASE + s)
        n_rej += (r["p"] < 0.05)
        detail.append(round(r["p"], 4))
    return n_rej, detail

if __name__ == "__main__":
    for blk in (40, 20, 10, 5):
        n, d = fp_rate(blk)
        print(f"块长 {blk:>2} 日 | 零差假阳性 {n}/{len(d)} (名义 1/20) | p 序列 {d}")
