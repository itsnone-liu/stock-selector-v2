"""T5.1 常量与版本。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t5/facts"

RULE_VERSION = "t5_1_facts_v1"
MAX_HORIZON = 40                 # delta_day 0..40（lifecycle_end 截断）
FWD_HORIZONS = (1, 3, 5, 10)     # 结果表短 horizon
FWD_PATH_HORIZONS = (5, 10)      # 峰值/MDD/失守窗
LOAD_EPS = 0.01                  # efficiency 分母下限（冻结，防极小分母）
PRE20_BASE_EPS = 1e-12

TERMINATION_REASONS = (
    "MAX_HORIZON",      # 达到 delta 40 上限（或 lifecycle 覆盖更长）
    "LIFECYCLE_END",    # 到达冻结 end_day
    "DATA_END",         # 市场日历/个股数据先于两者结束
)

# 允许进入 state 的字段族（G4 检查用）；outcome 表物理分离
STATE_FIELD_FAMILIES = ("idx", "price", "participation", "efficiency", "context")
