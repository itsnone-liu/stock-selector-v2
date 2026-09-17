"""信号层契约：快照、周线证据、日线证据、生命周期。

设计约束（资金效率与多周期动能重构方案 §2.2/§6）：
- 快照不可变：周线与日线共用同一份 as_of 时点证据；
- 证据先于判定：WeeklyEvidence/DailyEvidence 同时携带连续指标与判定结果；
- 判定必须可解释：每条规则输出生成它的数值（t_eff/l_eff 等），不允许只剩布尔值；
- unknown 不等于 false：数据不足时输出 unknown，不得计入失败事件；
- 快照构建禁止读取未来行情；收益关联只在独立的 outcome 阶段发生。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

UNKNOWN = "unknown"


@dataclass(frozen=True)
class MarketSnapshot:
    """as_of 时点的统一市场快照（周线与日线的共同输入）。"""

    code: str
    as_of: datetime
    evidence_level: str  # "L0" | "L1" | "L2"
    daily: pd.DataFrame  # 截至 as_of 的日线（不含当日未落盘数据时无当日行）
    current_bar: dict | None  # 当日 bar（来自日线或实时报价合成），键: open/high/low/close/volume/amount
    current_bar_source: str  # "daily_bar" | "realtime_synthetic" | "missing"
    quote_ts: datetime | None
    calendar_weekday: int
    session_ordinal_in_week: int | None  # 本周第几个交易日（真实日历）
    planned_sessions_this_week: int | None  # 本周计划交易日数（短周=4）
    week_completion: float | None  # 真实交易进度（基于计划交易日）；legacy 复刻用 /5 记录在别处
    missing_fields: tuple[str, ...] = ()

    @property
    def has_current_bar(self) -> bool:
        return self.current_bar is not None


@dataclass(frozen=True)
class WeekBar:
    """单根周K（完整或部分），保留量额与来源。"""

    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None
    sessions: int  # 构成该周的交易日的数
    complete: bool

    @property
    def is_yang(self) -> bool:
        return self.close > self.open

    @property
    def change_pct(self) -> float:
        return (self.close - self.open) / self.open * 100 if self.open else 0.0


@dataclass
class WeeklyEvidence:
    """周线证据：连续指标 + 形态判定 + 星期路径 + 风险标记。"""

    code: str
    as_of: datetime | None = None
    # 连续证据（先生成、供所有版本使用）
    realized_return_pct: float | None = None  # 本周已实现涨跌幅%
    volume_cumulative: float | None = None
    amount_cumulative: float | None = None
    efficiency_this_week: float | None = None  # t_eff
    efficiency_prev_week: float | None = None  # l_eff
    efficiency_delta: float | None = None
    efficiency_comparison_basis: str = UNKNOWN  # full_week | partial_prorated | same_progress
    volume_ratio_vs_prev_week: float | None = None
    prorated_volume_ratio: float | None = None  # /days×5 折算后的量比（legacy 口径）
    # Theory早周并行证据（只记录，不参与当前准入）
    same_progress_return_delta_pct: float | None = None
    same_progress_volume_ratio: float | None = None
    planned_prorated_return_pct: float | None = None
    planned_prorated_volume_ratio: float | None = None
    early_week_evidence_strength: float | None = None
    tuesday_recovery_ratio: float | None = None
    # 收盘对收盘动能上下文（2026-09-17裁定：所有比较用收盘vs前期收盘）
    prev_week_cc_pct: float | None = None      # 上一完整周 cc 涨幅%
    prev2_week_cc_pct: float | None = None     # 上上周 cc 涨幅%
    partial_week_cc_pct: float | None = None   # 本周至今收盘 vs 上周收盘
    momentum_context_positive: bool | None = None  # 前两周cc均>0；None=数据不足
    theory_stagnation_flag: bool | None = None  # 上涨早周的部分周滞涨（cc口径）
    week_sessions: int | None = None
    week_completion: float | None = None
    # 形态判定
    base_pattern: str = UNKNOWN  # negative_to_positive | double_positive_efficiency_improved | none | unknown
    weekday_path: str = UNKNOWN  # monday | tuesday_A | tuesday_B | tuesday_C | midweek_partial | completed_week
    passed: bool | None = None  # legacy 复刻判定（None=数据不足 unknown）
    # 四态准入契约：eligible | observation | excluded | unknown。
    # legacy只映射既有判定，不改变其语义；Theory/Optimized可独立给状态理由。
    eligibility_state: str = UNKNOWN
    eligibility_reason: str | None = None
    # 风险
    veto_flag: bool = False
    veto_metrics: dict = field(default_factory=dict)
    # 裁决可解释性
    components: dict = field(default_factory=dict)  # 分支各条件的数值结果
    notes: list[str] = field(default_factory=list)


@dataclass
class DailyEvidence:
    """日线证据：原版标签与优化特征并行输出。"""

    code: str
    as_of: datetime | None = None
    r_today: float | None = None
    r_yesterday: float | None = None
    return_acceleration: float | None = None
    today_volume: float | None = None
    yesterday_volume: float | None = None
    volume_ratio_vs_prev: float | None = None
    # 原版标签（含 3.5% 上限的原样复刻）
    legacy_labels: dict[str, bool | None] = field(default_factory=dict)
    raw_pattern_matched: dict[str, bool | None] = field(default_factory=dict)  # 上限前的量价现象
    # 优化特征（独立命名，不占用原版标签名）
    optimized_labels: dict[str, bool | None] = field(default_factory=dict)
    atr14_previous: float | None = None
    atr_normalized_move: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Episode:
    """动能状态生命周期：首次触发、确认、失效、重触发。"""

    episode_id: str
    code: str
    kind: str  # weekly_momentum | daily_trigger | ...
    first_observed_at: datetime | None = None
    last_confirmed_at: datetime | None = None
    confirmation_delay_sessions: int | None = None
    invalidated_at: datetime | None = None
    retriggered_at: datetime | None = None
    consecutive_confirmations: int = 0
    previous_state: str = UNKNOWN
    current_state: str = UNKNOWN
    transition_reason: str | None = None
