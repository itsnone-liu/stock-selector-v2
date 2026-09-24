#!/usr/bin/env python3
"""T5.1 语义勘误记录脚本（正式 erratum，2026-09-24 用户验收裁决）。

不重建任何数据；仅将三条规范写入冻结产物 JSON：
1. delta_day = 市场交易日时间推进（停牌不压缩，V3 一致）
2. row_present = source/calendar row exists（非 tradability）
3. LOAD_EPS = denominator-validity guard（missing + explicit reason）
本脚本幂等，重复执行结果一致，作为勘误的可审计载体。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t5/facts"

ERRATUM = {
    "issued_by": "user_acceptance_T5.1_2026-09-24",
    "scope": "specification clarification only; no data rebuild",
    "delta_day": ("从 breakout_day 开始的市场交易日相对时间推进。"
                  "个股停牌时 delta 继续前进、不压缩时间、不把停牌日"
                  "视为有效成交观察（与 V3 tau 时间语义一致，"
                  "T5.2 起沿用不再更改）。"),
    "row_present": ('"source/calendar row exists" 而非 '
                    '"stock was tradable"。交易/价格/参与变量能否使用'
                    '必须读取各自 validity flag（adj_available / '
                    'volume_valid）。本数据源中停牌表现为量能/复权'
                    '无效行而非日历缺行（row_present=False 为 0 行）。'),
    "load_eps": ("LOAD_EPS=0.01 仅为 denominator-validity guard。"
                 "触发时 value=missing 且 missing_reason="
                 '"denominator_below_eps"；禁止转为 0/1 或任何状态类别'
                 "（T5.2 起作为字段级约束执行）。"),
}


def main():
    man = json.loads((OUT / "t5_1_manifest.json").read_text())
    man["semantic_erratum"] = ERRATUM
    (OUT / "t5_1_manifest.json").write_text(json.dumps(
        man, indent=2, ensure_ascii=False))

    dic = json.loads((OUT / "t5_primitive_dictionary.json").read_text())
    dic["semantic_erratum"] = ERRATUM
    dic["index"]["delta_day"]["formula"] = (
        "从 breakout_day 开始的市场交易日相对时间推进（停牌不压缩）")
    dic["index"]["row_present"]["formula"] = (
        "source/calendar row exists（非 tradability；停牌用 "
        "volume_valid/adj_available 表达）")
    dic["efficiency"]["efficiency_signed_{1,3}"]["missing_semantics"] = (
        "分母不足(Σload<0.01, missing_reason=denominator_below_eps)"
        "或价格缺→None；不得转 0/1")
    (OUT / "t5_primitive_dictionary.json").write_text(json.dumps(
        dic, indent=2, ensure_ascii=False))
    print("erratum applied (idempotent)")


if __name__ == "__main__":
    main()
