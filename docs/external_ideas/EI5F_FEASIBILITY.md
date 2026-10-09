# EI-5F Intraday 数据与成本可行性（2026-10-09 冻结结构，F0 已执行）
四问：F1 数据够(1m OHLCVA+竞价即可，不需L2) / F2 历史≥2个完整年度+跨regime+cohort覆盖≥90% / F3 价格(倾向最后买：QMT>TDX本地>Tushare 2000/年+竞价500) / F4 新信息须事前冻结=Price Impact Efficiency(PE1=位移/amount, PE2=向上位移/volume, PE3=回撤量/推进量；禁指标矿场)。
GO门：历史≥2年∧覆盖≥90%∧1m量价稳定∧时间戳/复权/停牌语义统一∧成本合理∧生产有可持续实时源 → 开EI-5A。
历史不足但采集稳 → EI-5P prospective-only（只收不判）。
严重残缺/对不上账/须L2 → DATA-INFEASIBLE/DEFERRED。

## F0 现有资源盘点结果（2026-10-09，0元）
1. 本地TDX镜像 /root/tdx_data/vipdoc：sh/sz minline、fzline 目录存在但 **0 文件**——镜像只同步 lday（日线）。lc1/lc5 历史深度=零。
2. QMT/xtquant：本机未安装，无 1m/tick 权限可查。
3. Tushare：未安装未采购。
4. 日更链路：仅日线自动；分钟无任何自动化。
结论：三条免费路线两条为零。唯一0元解锁路径=数据源端TDX终端机开启分钟下载（minline/fzline 会在终端盘后写盘），镜像扩同步 lc1/lc5——属部署侧动作。当前状态：EI-5 = DEFERRED，待源端分钟数据到位或批准 2500 元采购后重开 F2 bake-off。EI-5P prospective 采集可在源端开启下载当日立即启动（无回填）。
