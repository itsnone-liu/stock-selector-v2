# RULE_EQUIVALENCE_MATRIX（规则对照表）

复刻版 signals/weekly_features.py ↔ 旧 week_surge.py v4.0（.hermes 副本）。

| 规则 | 旧代码位置 | 复刻实现 | 差分验证 |
|---|---|---|---|
| 形态B双阳效率 | check_dual_yang L180-204 | dual_yang_efficiency() | 900/900 |
| 形态A阴转阳 | check_reversal L174-178 / 各分支内联 | reversal_check() | 900/900 |
| veto v4.0 | bearish_heavy_turnover_veto L124-163 | bearish_heavy_veto() | 900/900（含分发层前置） |
| 周一分支 | check_surge_monday L166-226 | evaluate_monday(partial) | 178/178 |
| 周二三情形 | check_surge_tuesday L229-297 | evaluate_tuesday() | 153/153 |
| 周三四折算 | check_surge_wednesday_thursday L300-377 | evaluate_midweek() | 388/388 |
| 周五完整周 | check_surge_friday L380-427 | evaluate_friday() | 181/181 |
| 死代码（前推一组重复传参） | L215-224 | 不复刻 | 取证已判死代码 |
| 周三四周三情形窗口 | this_week_start = index[-1] - weekday 天 | current_week_rows | 见 KNOWN_DIFFERENCES D1 |

效率公式（逐字段）：tc=|本周涨幅%|（周三四用折算值）、lc=|上周涨幅%|、
tv_ratio=本周量/上周量（周三四用折算量）、t_eff=tc/tv_ratio、l_eff=lc、
通过条件 t_eff>l_eff（且双阳）。形态A：上周阴+本周阳，无量比要求。
veto：最后周bar收阴 且 amount(缺则volume)>前4周均值×1.5。
