#!/usr/bin/env python3
"""T5.1 逐日 PIT 事实层构建（A-E 分批一次执行）。

产物：t5_daily_state / t5_daily_outcome / t5_primitive_dictionary /
t5_coverage / t5_1_manifest。十道 Gate 见 gate_t5_1.py。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from t5 import primitives_build as B          # noqa: E402
from t5 import outcomes as OC                 # noqa: E402
from t5.constants import OUT, RULE_VERSION, MAX_HORIZON  # noqa: E402
from t5.schemas import dump_dictionary, STATE_COLS, OUTCOME_COLS  # noqa

BASELINE = "3f10a96"


def frame_hash(df: pd.DataFrame, keys) -> str:
    h = hashlib.sha256()
    d = df.sort_values(list(keys)).reset_index(drop=True)
    h.update(d.to_csv(index=False).encode("utf-8"))
    h.update(str(d.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != {BASELINE}"
    OUT.mkdir(parents=True, exist_ok=True)
    t0w = time.time()

    events = B.load_events_with_inheritance()
    mkt = B.load_market_daily()
    mdates = B.load_market_calendar()
    print(f"[t5.1] inputs events={len(events)} mdates={len(mdates)} "
          f"{time.time() - t0w:.0f}s", flush=True)

    stocks = list(B.iter_stock_full())
    print(f"[t5.1] stocks loaded={len(stocks)} {time.time() - t0w:.0f}s",
          flush=True)

    state = B.build_dynamic_state(events, mkt, stocks, mdates)
    state = state.sort_values(["event_id", "delta_day"]).reset_index(
        drop=True)
    state.to_parquet(OUT / "t5_daily_state.parquet", index=False)
    print(f"[t5.1] state {state.shape} {time.time() - t0w:.0f}s", flush=True)

    oc = OC.build_dynamic_outcomes(
        state[["event_id", "code", "breakout_day", "delta_day",
               "state_date", "row_present"]], stocks, mdates)
    oc = oc.sort_values(["event_id", "delta_day"]).reset_index(drop=True)
    oc.to_parquet(OUT / "t5_daily_outcome.parquet", index=False)
    print(f"[t5.1] outcome {oc.shape} {time.time() - t0w:.0f}s", flush=True)

    dump_dictionary(OUT / "t5_primitive_dictionary.json")

    # coverage：年份 × 相对日 × E 档
    cov = (state.groupby(["year", "delta_day", "exposure_class"])
           .size().rename("n").reset_index())
    cov.to_parquet(OUT / "t5_coverage.parquet", index=False)

    # 与 V3 冻结对照（G 素材：cum_ret_from_t0_log ↔ close_rel_t0_log）
    v3 = pd.read_parquet(ROOT / "output/research/t3_v3/"
                         "event_path_daily.parquet",
                         columns=["breakout_event_id", "tau",
                                  "close_rel_t0_log", "row_present",
                                  "max_drawdown_to_tau"])
    chk = state.merge(v3, left_on=["event_id", "delta_day"],
                      right_on=["breakout_event_id", "tau"], how="inner")
    both = chk.dropna(subset=["cum_ret_from_t0_log",
                              "close_rel_t0_log"])
    max_diff = float((both["cum_ret_from_t0_log"]
                      - both["close_rel_t0_log"]).abs().max())
    rp = bool((chk["row_present_x"] == chk[
        "row_present_y"]).all()) if len(chk) else False
    reconc = {"rows_joined": int(len(chk)), "rows_state": int(len(state)),
              "cum_ret_max_abs_diff": max_diff,
              "row_present_identical": rp}

    det = {"state_hash": frame_hash(state, ["event_id", "delta_day"]),
           "outcome_hash": frame_hash(oc, ["event_id", "delta_day"])}
    manifest = {
        "stage": "T5.1_facts", "rule_version": RULE_VERSION,
        "baseline_commit": BASELINE,
        "inputs": {
            "events": "t4_exposure_assignment (27,422) + "
                      "t4_context_state (end_day/pre20 bases) + "
                      "t4_6c risk budget classes",
            "market": "t4/context market_daily.parquet (T4.1 冻结)",
            "stocks": "data/adjustment_baostock/per_stock + "
                      "adjustment_v1 factor_table",
            "calendar": "sh999999.day 指数日历（V3 tau 同源）"},
        "semantics": {
            "delta_day": "市场交易日序号相对 T0，与 V3 tau 同源",
            "expansion": "0..min(40, lifecycle_end, 日历末)",
            "row_present": "state_date ∈ 个股交易日（停牌=False 不补值）",
            "participation_denominator":
                "事件级 pre20 冻结基数（T4.2 继承，不重算）",
            "efficiency_eps": "LOAD_EPS=0.01 分母下限（冻结）",
            "outcome_censor":
                "个股有效交易日计数；不完整窗口 complete=False 不作零"},
        "rows": {"state": len(state), "outcome": len(oc)},
        "v3_reconciliation": reconc,
        "determinism": det,
        "elapsed_sec": round(time.time() - t0w, 1),
        "not_implemented": ["C0-C6 候选状态", "动作资格", "仓位优化",
                            "T5.2-T5.6"],
        "known_gaps": ["板块 PIT 背景缺冻结数据，未引入（不以回溯表充当）"],
    }
    (OUT / "t5_1_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps({"rows": manifest["rows"], "v3": reconc,
                      "elapsed": manifest["elapsed_sec"]}, indent=2),
        flush=True)


if __name__ == "__main__":
    main()
