#!/usr/bin/env python3
"""T5.2 状态定义构建（Development = 2024 only；任务书 §七阈值纪律）。

生成 t5_state_definition.json：
- rules：C0–C6 候选语义规则（字段/op/阈值来源四分类）
- priority_order：显式优先级（C6>C5>C4>C1>C3>C2>C0）
- dev_quantiles：delta-conditioned 分位参考表（仅 dev=2024 生成）
- eligibility / missing rule / code_version

candidate_state_v1 与 v2 的唯一语义级差异：
  v2 的 C6 增加深回撤分支（drawdown ≥ delta-q95），
  v2 的 C4 用推进不足三分支替代单一 days_since_peak。
不读取 outcome。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "output/research/t5/state"
OUT.mkdir(parents=True, exist_ok=True)

DEVQ_FIELDS = ["drawdown_from_peak_log", "max_dd_to_date_log",
               "days_since_peak", "efficiency_signed_3", "ret_5d_log",
               "cum_ret_from_t0_log"]
DEVQ_QS = ["q25", "q50", "q60", "q70", "q75", "q90", "q95"]
QN = {"q25": 0.25, "q50": 0.50, "q60": 0.60, "q70": 0.70,
      "q75": 0.75, "q90": 0.90, "q95": 0.95}

EVIDENCE = ["cum_ret_from_t0_log", "drawdown_from_peak_log",
            "max_dd_to_date_log", "days_since_peak", "dist_to_ref20",
            "ret_3d_log", "ret_5d_log", "efficiency_signed_3",
            "turnover_load_3d_mean", "turnover_contraction_3d",
            "is_new_high_20d", "new_high_count_since_t0"]


def build_dev_quantiles():
    st = pd.read_parquet(ROOT / "output/research/t5/facts/"
                         "t5_daily_state.parquet",
                         columns=["delta_day", "year"] + DEVQ_FIELDS)
    dev = st[st["year"].astype(str) == "2024"]
    table = {}
    for f in DEVQ_FIELDS:
        g = dev.groupby("delta_day")[f]
        table[f] = {}
        for d, ser in g:
            table[f][str(int(d))] = {
                qn: (None if ser.isna().all()
                     else round(float(ser.quantile(QN[qn])), 6))
                for qn in DEVQ_QS}
    return table


def rules_v1(dq):
    dd = "drawdown_from_peak_log"
    return {
        "C6": {"semantic": "structural_break_ref20_lost",
                "conditions": {"dist_to_ref20": {
                    "kind": "anchor", "op": "<", "value": 0.0,
                    "source": "natural anchor: close_raw < ref20"}}},
        "C5": {"semantic": "decay_low_efficiency_high_damage",
                "conditions": {
                    "efficiency_signed_3": {
                        "kind": "devquant", "op": "<", "q": "q25",
                        "source": "dev2024 delta-conditioned q25"},
                    dd: {"kind": "devquant", "op": ">=", "q": "q75",
                         "source": "dev2024 delta-conditioned q75"}}},
        "C4": {"semantic": "stagnation_long_no_progress",
                "conditions": {
                    "days_since_peak": {"kind": "devquant", "op": ">=",
                                        "q": "q75",
                                        "source": "dev2024 q75"},
                    "ret_5d_log": {"kind": "devquant", "op": "<=",
                                   "q": "q50",
                                   "source": "dev2024 q50"}}},
        "C1": {"semantic": "strong_continuation_new_high_low_damage",
                "conditions": {
                    "is_new_high_20d": {"kind": "anchor", "op": "==",
                                        "value": True,
                                        "source": "21-window new high"},
                    dd: {"kind": "devquant", "op": "<=", "q": "q50",
                         "source": "dev2024 q50"},
                    "cum_ret_from_t0_log": {"kind": "anchor", "op": ">",
                                            "value": 0.0,
                                            "source": "above T0"}}},
        "C3": {"semantic": "recovery_from_prior_damage",
               "conditions": {
                   "max_dd_to_date_log": {"kind": "devquant", "op": ">=",
                                          "q": "q75",
                                          "source": "dev2024 q75"},
                   "ret_3d_log": {"kind": "anchor", "op": ">",
                                  "value": 0.0,
                                  "source": "positive 3d momentum"},
                   "repairing": {"kind": "predicate",
                                 "predicate": "repairing",
                                 "source": "current dd below "
                                           "historical max (repairing)"}}},
        "C2": {"semantic": "healthy_pullback_structure_intact",
               "conditions": {
                   dd: {"kind": "devquant", "op": ">=", "q": "q75",
                        "source": "dev2024 q75"},
                   "participation_ok": {"kind": "predicate",
                                        "predicate": "participation_ok",
                                        "source": "contraction_3d==True "
                                                  "or load_3d_mean<=1.0 "
                                                  "(pre20 base anchor)"}}},
    }


def rules_v2(dq):
    r = rules_v1(dq)
    r["C6"]["semantic"] = "structural_break_ref20_or_deep_drawdown"
    r["C6"]["conditions"] = {
        "c6_break_v2": {"kind": "predicate", "predicate": "c6_break_v2",
                        "source": "v2: dist_to_ref20<0 OR "
                                  "drawdown>=delta_q95"}}
    r["C4"]["semantic"] = "stagnation_time_or_progress_deficit"
    r["C4"]["conditions"] = {
        "c4_stall_v2": {"kind": "predicate", "predicate": "c4_stall_v2",
                        "source": "v2: days_since_peak>=q75 OR "
                                  "(cum_ret<=q25 AND delta>=10)"}}
    return r


def make_definition(version: str, dq: dict) -> dict:
    rules = rules_v1(dq) if version == "v1" else rules_v2(dq)
    return {
        "code_version": f"t5_2_candidate_state_{version}",
        "rule_version_note": "candidate; NOT a level ordering; "
                             "no action semantics (T5.4 pending)",
        "axes": ["P", "D", "V", "E", "R"],
        "priority_order": ["C6", "C5", "C4", "C1", "C3", "C2", "C0"],
        "c0_early_delta": 5,
        "rules": rules,
        "eligibility": {
            "all_of": ["adj_available"],
            "non_null": ["dist_to_ref20", "drawdown_from_peak_log",
                         "max_dd_to_date_log"],
            "reason_map": {
                "adj_available": "adj_unavailable",
                "dist_to_ref20": "ref20_missing",
                "drawdown_from_peak_log": "price_missing",
                "max_dd_to_date_log": "price_missing"}},
        "evidence_fields": EVIDENCE,
        "dev_quantiles": dq,
        "devquant_scope": "breakout_year==2024 only",
        "threshold_sources": {
            "anchor": ["dist_to_ref20<0", "ret_3d>0", "cum_ret>0",
                       "is_new_high_20d", "load_3d_mean<=1.0"],
            "frozen": ["dd<max_dd (repairing)",
                       "contraction or load<=1",
                       "v2 C6/C4 composite"],
            "devquant": "delta-conditioned q25/q50/q75/q95 from dev2024",
            "nodrift": "ret_1/3/5d 与 efficiency 分布平稳（audit 已证），"
                       "阈值仅经 devquant 引用",
        },
        "missing_rule": "any required field missing -> rule not "
                        "evaluable; all unevaluable or ineligible -> "
                        "STATE_UNAVAILABLE + reason (never neutral "
                        "fill into C0)",
    }


def main():
    dq = build_dev_quantiles()
    for v in ("v1", "v2"):
        d = make_definition(v, dq)
        h = hashlib.sha256(json.dumps(d, sort_keys=True).encode()
                           ).hexdigest()
        d["definition_sha256"] = h
        p = OUT / f"t5_state_definition_{v}.json"
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        print(v, "sha256", h[:16], "->", p.name)
    # 正式 definition（v1 进入验证；G7 冻结点）
    import shutil
    shutil.copy(OUT / "t5_state_definition_v1.json",
                OUT / "t5_state_definition.json")


if __name__ == "__main__":
    main()
