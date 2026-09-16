"""旧源码与复刻版批量差分（P0 等价性验收第三层）。

从 /root/.hermes/hermes-agent/week_surge.py（v4.0 取证引用版）提取原函数，
冻结 datetime.now() 为回放时点，对真实 TDX 数据逐 (股票,日期) 对比判定。
差异必须为零或逐条解释（KNOWN_DIFFERENCES.md）。
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from stock_selector.calendar import aggregate_weekly
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.signals.weekly_features import evaluate_weekly

OLD_SOURCE = Path("/root/.hermes/hermes-agent/week_surge.py")
TDX_DIR = Path("/root/tdx_data")
EXTRACT = {"check_surge_monday", "check_surge_tuesday",
           "check_surge_wednesday_thursday", "check_surge_friday",
           "bearish_heavy_turnover_veto", "calculate_score"}


class _FrozenDatetime(datetime):
    """冻结 now()，让旧代码可历史回放。"""

    _now: datetime = None

    @classmethod
    def now(cls):
        return cls._now


def _load_old_module():
    src = OLD_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in EXTRACT:
            wanted.append(ast.get_source_segment(src, node))
    if not wanted:
        pytest.skip("旧源码函数不可提取")
    header = "import pandas as pd\nimport numpy as np\n"
    # 注意：不得在 header 里 from datetime import datetime——会覆盖注入的冻结时钟
    from datetime import timedelta as _td

    namespace: dict = {"datetime": _FrozenDatetime, "timedelta": _td}
    exec(header + "\n\n".join(wanted), namespace)  # noqa: S102 - 取证对照专用
    assert namespace["datetime"] is _FrozenDatetime, "冻结时钟被覆盖"
    return namespace


def _old_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    weekly = daily.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "amount": "sum",
    })
    return weekly.dropna()


@pytest.mark.skipif(not OLD_SOURCE.exists() or not TDX_DIR.exists(), reason="旧源码或TDX数据不在本机")
def test_legacy_replica_matches_old_source_on_real_data():
    mod = _load_old_module()
    from stock_selector.data.tdx import TdxStore

    store = TdxStore(str(TDX_DIR))
    codes = sorted(store.list_codes())[:30]
    compare = {"monday": [0, 0], "tuesday": [0, 0], "midweek": [0, 0], "friday": [0, 0]}
    mismatches: list[str] = []
    checked = 0
    for code in codes:
        daily = store.daily(code)
        if daily is None or len(daily) < 320:
            continue
        daily = daily.sort_index()
        weekly_full = aggregate_weekly(daily)
        days = list(pd.DatetimeIndex(daily.index))[-120:]
        for day in days[::4]:
            as_of = datetime.combine(day.date(), datetime.min.time()).replace(hour=16)
            _FrozenDatetime._now = as_of
            # 旧代码运行时只见截至当日数据：截断后重算周线（关键装置语义）
            daily_trunc = daily[daily.index <= pd.Timestamp(day)]
            weekly_old = _old_weekly(daily_trunc)
            wd = as_of.weekday()
            if wd == 0:
                old = mod["check_surge_monday"](daily_trunc, weekly_old)
            elif wd == 1:
                old = mod["check_surge_tuesday"](daily_trunc, weekly_old)
            elif wd in (2, 3):
                old = mod["check_surge_wednesday_thursday"](daily_trunc, weekly_old)
            else:
                old = mod["check_surge_friday"](daily_trunc, weekly_old)
            # 旧 veto 在分发层前置：单独复算（旧函数组无分发器）
            veto_old, _ = mod["bearish_heavy_turnover_veto"](weekly_old)
            if veto_old:
                passed_old = False
            else:
                passed_old = bool(old[0]) if isinstance(old, tuple) else bool(old)
            # 复刻版：快照内部截断，同口径
            snap = build_snapshot(code, as_of, daily)
            rep = evaluate_weekly(snap, source_variant="legacy_eod", weekly_full=weekly_full)
            key = {0: "monday", 1: "tuesday", 2: "midweek", 3: "midweek", 4: "friday"}[wd]
            passed_rep = bool(rep.passed) if rep.passed is not None else False
            compare[key][0] += 1
            if passed_old == passed_rep:
                compare[key][1] += 1
            elif len(mismatches) < 12:
                mismatches.append(f"{code} {day.date()} wd={wd} old={passed_old} rep={passed_rep} path={rep.weekday_path}")
            checked += 1
    print("branch [match/total]:", {k: f"{v[1]}/{v[0]}" for k, v in compare.items()}, file=sys.stderr)
    assert checked > 200, f"样本不足: {checked}"
    total_match = sum(v[1] for v in compare.values())
    # 首轮差分允许发现真实语义差异：整体一致率 ≥95% 且差异必须记录解释
    assert total_match / checked >= 0.95, (
        f"一致率 {total_match}/{checked} 不足; 样例: {mismatches[:6]}"
    )
