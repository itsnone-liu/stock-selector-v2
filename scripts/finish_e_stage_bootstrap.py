#!/usr/bin/env python3
"""已废弃：旧E阶段 eligible-vs-all-noneligible 混合对照禁止继续运行。

正式统计必须消费 build_research_design.py / run_e_stage_analysis.py 生成的
三类 progressive design cohort，并在明确组间做两两比较。保留此文件仅用于
阻止旧自动化或人工命令静默覆盖 e_stage_bootstrap.json。
"""
raise SystemExit(
    "obsolete mixed-control bootstrap is disabled; rebuild a v3 panel and use explicit designs/ cohorts"
)
