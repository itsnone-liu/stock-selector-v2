# EI-4 VWAP Cost Proxy — 预注册（冻结于执行前）
纯工程近似检验：多周期 VWAP 能否近似 Full Cost Band（500日/30%量/最窄带）。非 alpha 研究。
代理定义（事前冻结）：vwap_N=Σ(typ·vol)/Σvol（N=120,250）；proxy_mid=(vwap120+vwap250)/2；proxy_band=[min(v120,v250)×0.95, max×1.05]；状态 IN=带内, UNDERCUT=<low但≥low×0.95×, BREAK_WARN=5日收盘<low×0.95。
样本：随机800股(seed42)×近24个月末时点。对照指标：DTC 相关 / 四态一致率 / 代理状态对"真实BROKEN(全带口径,60日内)"的排序保留（IN<UNDERCUT<WARN 单调且 WARN 组真实破位率≥2×IN组）。
判定：一致率≥70% ∧ 排序单调保留 → 可作盘中轻量层；否则 ARCHIVED（只画图）。单次执行。

## 结果（2026-10-09 单次执行，n=18,087 股×月末）
四态一致率 57.4%（<70% 线）｜DTC 相关 0.63｜破位预警一致率 87.7%｜排序：proxy-IN 25.4% < proxy-UNDERCUT 20.3%（**倒挂**）< proxy-BELOW 65.6%（单调性破坏）。
## 判定：EI-4 = FAIL / ARCHIVED（只作图表辅助）
VWAP 双周期代理保不住 support 状态语义：一致率不足、UNDERCUT 桶对真实 60 日破位率与 IN 桶倒挂（VWAP 滞后让"带下试探"与"带内"混同）。盘中轻扫继续用冻结 Full Band（每晚重建一次、盘中只查带不动带），不引入 VWAP 近似层。不救（不换窗口/不加周期/不加自适应系数）。
