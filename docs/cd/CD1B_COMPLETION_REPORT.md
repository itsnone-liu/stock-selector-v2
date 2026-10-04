# CD-1B — PIT Sector Infrastructure · Completion Report

*预注册: `cd1b_preregistration.json`（commit df87b1b）· 运行记录: `cd1b_axes_run.json` · 数据: `data/cd/sector_axes/l2_four_axes.json.gz`（gitignored）*

## 交付物

**四轴可观测量表**：115,619 行 = 83 L2 板块 × 1,393 交易日（2021-01-04→2026-09-30），每行一个 (sector, date) cell，纯函数于 (DATA-1 5430 文件, csrc_v1 v1-static membership)。

**确定性验证：双跑字节一致**（sha256_rows `0f747662efa35818…`，两遍独立全量 186s/185s）。

## 行状态分布（fail-closed 合同）

| 状态 | 行数 | 说明 |
|---|---|---|
| OK | 98,013 (84.8%) | ≥5 参与成员，全字段计算 |
| INSUFFICIENT_PARTICIPATION | 17,604 (15.2%) | <5 参与成员的小板块日（如 A02/B10 等 <5 成员板块全期） |
| NO_TRADING_MEMBERS | 2 | O81（综合）2026-03-30/31 全体成员停牌，显式发射 |

## 四轴字段（全部预注册后计算，无自由度漂移）

**Relative Performance**：sector_eq/sector_vw、mkt_eq/mkt_vw、rel_eq_mkt / rel_vw_mkt / rel_eq_parent / rel_vw_parent（vs 市场 & vs L1 父类双基准）
**Participation**：vol_share、vol_share_20d（trailing 20 日均值，含 T；volume 为 DECLARED amount 替代）
**Breadth**：advance_frac、vol_confirmed_frac（vs 自身前 20 日均量，严格不含 T）、new_high_frac（60 日新高，含 T）
**Concentration**：ret_contrib_top3/top5（正贡献集中度，零分母→NULL）、vol_top3/top5、top5_mean_ret / rest_mean_ret（escalation 规格输入）

## 质量（98,013 OK 行）

- 71/83 板块至少有一天 OK（其余 12 个为 <5 成员板块，全期 INSUFFICIENT，诚实保留不合并）
- 参与成员 min/median/max = 5 / 29 / 665
- NULL 率：rel_eq_mkt = 0、vol_share_20d = 0、vol_confirmed_frac = 0；ret_contrib_top3 = 4.1%（当日无正贡献板块，NULL 不插补）；top5_mean_ret = 2.6%（板块仅 5-6 只参与者）

## PIT 纪律

全部窗口 trailing-only（20d/60d 回看止于 T 含 T）；无 forward return 字段；表内无任何评分/排序。qfq 收益经 model_derived adjust_factor（锚定最新=1，声明于 DATA-1）。

## L3-A 层（非阻塞，已就绪）

申万二级 `sw2_v1_static_declared`（131 指数 / 5220 股完美不相交 / 覆盖 99.94% / census 全 PASS，commit e3ad58f）——替代 TDX 路线（官网下载链被 JS 隐藏 + fk.tdx.com.cn 私有 TQL 协议 + download 域不可达，如实放弃并记录）。按粒度合同：仅作 L2_INTERNAL_HETEROGENEITY 触发时的当前分解层；任何倒灌历史用途必须标 RETROSPECTIVE_GROUPING 且禁作历史主信号。

## 未做（按裁定/预注册）

- 最终强弱评分、板块排序、市场结论 → CD-2+ 且需独立预注册
- escalation 触发阈值操作化 → 由消费方阶段定义
- L3_STATIC_BACKCAST_RISK_AUDIT → 记录未启动
- amount/turnover/free_float/ST 缺口补抓 → EM 解封后

**全局状态**：`CD-0 FROZEN · CD-1A COMPLETE · CD-1B COMPLETE (axes table + determinism PASS) · CD-2 NOT STARTED（待 GO）· CSR-8 不变`
