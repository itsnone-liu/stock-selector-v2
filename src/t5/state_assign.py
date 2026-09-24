"""T5.2 状态赋值引擎（规则表驱动，PIT，不 import outcome）。

纪律（任务书 §三/§七/§九/§十）：
- 规则、阈值、优先级全部从 t5_state_definition.json 读入；
  引擎只实现具名谓词（predicate），不含数值阈值；
- 每条规则所需字段任一缺失 -> 该规则 not_evaluable；
  全部规则 not_evaluable 或行不 eligible -> STATE_UNAVAILABLE+reason；
- matched_rules 全列表 + priority_resolution 显式输出；
- 不读取、不连接 t5_daily_outcome（G4）。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

STATE_UNAVAILABLE = "STATE_UNAVAILABLE"

# 具名谓词：required fields + 求值（阈值一律来自 definition/devq）
PREDICATES = {
    "repairing": {
        "fields": ["drawdown_from_peak_log", "max_dd_to_date_log"],
        "eval": lambda row, dq: row["drawdown_from_peak_log"]
        < row["max_dd_to_date_log"]},
    "participation_ok": {
        "fields": ["turnover_contraction_3d", "turnover_load_3d_mean"],
        "eval": lambda row, dq: (
            bool(row["turnover_contraction_3d"])
            if row["turnover_contraction_3d"] is not None
            and not _isnan(row["turnover_contraction_3d"])
            else False)
        or (row["turnover_load_3d_mean"] is not None
            and not _isnan(row["turnover_load_3d_mean"])
            and row["turnover_load_3d_mean"] <= 1.0)},
    "c6_break_v2": {
        "fields": ["dist_to_ref20", "drawdown_from_peak_log"],
        "eval": lambda row, dq: (
            row["dist_to_ref20"] < 0
            or row["drawdown_from_peak_log"] >= _dq(
                dq, "drawdown_from_peak_log", row["delta_day"], "q95"))},
    "c4_stall_v2": {
        "fields": ["days_since_peak", "cum_ret_from_t0_log",
                   "delta_day"],
        "eval": lambda row, dq: (
            row["days_since_peak"] >= _dq(dq, "days_since_peak",
                                          row["delta_day"], "q75")
            or (row["cum_ret_from_t0_log"] <= _dq(
                dq, "cum_ret_from_t0_log", row["delta_day"], "q25")
                and row["delta_day"] >= 10))},
}


def _isnan(v):
    try:
        return v is None or (isinstance(v, float) and np.isnan(v))
    except TypeError:
        return False


def _miss(v):
    return v is None or _isnan(v)


def _dq(dq, field, delta, q):
    return dq.get(field, {}).get(str(int(delta)), {}).get(q)


class StateAssigner:
    def __init__(self, definition: dict):
        self.defn = definition
        self.version = definition["code_version"]
        self.priority = definition["priority_order"]
        self.rules = definition["rules"]
        self.evidence_fields = definition.get("evidence_fields", [])
        self.elig = definition.get("eligibility")
        self.devq = definition.get("dev_quantiles", {})

    # ------------------------------------------------------------
    def _eval_rule(self, rule, row):
        missing, hit = [], True
        for field, spec in rule["conditions"].items():
            if spec.get("kind") == "predicate":
                name = spec["predicate"]
                pred = PREDICATES[name]
                for f in pred["fields"]:
                    if _miss(row.get(f)):
                        missing.append(f"{field}({f})")
                        break
                else:
                    hit &= bool(pred["eval"](row, self.devq))
                continue
            v = row.get(field)
            if _miss(v):
                missing.append(field)
                continue
            if spec["kind"] == "devquant":
                thr = _dq(self.devq, field, row["delta_day"], spec["q"])
                if thr is None:
                    missing.append(f"{field}@{spec['q']}")
                    continue
            else:                       # anchor / frozen / nodrift
                thr = spec["value"]
            op = spec["op"]
            hit &= bool({"<": v < thr, "<=": v <= thr,
                         ">": v > thr, ">=": v >= thr,
                         "==": bool(v) == bool(thr)}[op])
        if missing:
            return None, missing
        return bool(hit), []

    def assign_frame(self, st: pd.DataFrame) -> pd.DataFrame:
        recs = []
        for row in st.to_dict("records"):
            unavail = None
            for f in self.elig["all_of"]:
                if not bool(row.get(f, False)):
                    unavail = "adj_unavailable"
                    break
            if unavail is None:
                for f in self.elig["non_null"]:
                    if _miss(row.get(f)):
                        unavail = self.elig["reason_map"].get(
                            f, f + "_missing")
                        break
            if unavail is not None:
                recs.append(self._rec(row, STATE_UNAVAILABLE, False,
                                      "ineligible:" + unavail, "", ""))
                continue
            matched, uneval = [], []
            for code in self.priority:
                if code == "C0":
                    continue
                h, miss = self._eval_rule(self.rules[code], row)
                if h is None:
                    uneval.extend(f"{code}:{m}" for m in miss)
                elif h:
                    matched.append(code)
            if matched:
                final = matched[0]
                recs.append(self._rec(
                    row, final, True,
                    self.rules[final]["semantic"],
                    "|".join(matched),
                    "priority:" + ">".join(matched)
                    if len(matched) > 1 else "single"))
            else:
                # 无可评规则命中：基本信号（dd/dist_ref20）已过
                # eligibility，可判"无明显损伤" -> C0 兜底。
                # warmup 导致部分规则不可评仅记录，不产生 UNAVAILABLE
                # （C0 判据字段可得即"可判断"，见任务书 §十的
                #  "无法判断"边界；uneval 明细进 reason 供审计）。
                if row["delta_day"] <= self.defn.get("c0_early_delta", 5):
                    why = "early_warmup"
                elif uneval:
                    why = "warmup_partial_uneval:" + ";".join(
                        uneval[:2])
                else:
                    why = "no_dominant_pattern"
                recs.append(self._rec(row, "C0", True, why, "", "default"))
        return pd.DataFrame(recs)

    def _rec(self, row, state, assignable, reason, matched, resolution):
        r = {"event_id": row["event_id"], "delta_day": row["delta_day"],
             "candidate_state": state,
             "state_assignable": assignable,
             "state_reason": reason,
             "matched_rules": matched,
             "priority_resolution": resolution}
        for f in self.evidence_fields:
            r[f"ev_{f}"] = row.get(f)
        return r


def load_definition(path) -> StateAssigner:
    with open(path) as f:
        return StateAssigner(json.load(f))
