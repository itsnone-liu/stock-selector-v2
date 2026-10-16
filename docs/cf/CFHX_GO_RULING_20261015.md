# CF-HX Historical External Census — GO 裁决存档（用户 2026-10-15 深夜）

*Authority:* 用户外部情报普查裁决 · *边界:* **不改变 CF-1 已冻结合同**；CF-HX 是并行数据 census 扩展，与 CF-1A 自动采样互不阻塞

## 一、裁决背景

用户外部搜索修正判断：**L1/M/L4/L3 部分/L2-C 部分的历史可大量重建**（官方回填 + GitHub 已有历史库 + PIT 尽可能重建 + 实时采样补强，同时开始）；真正缺历史的只剩 L2-A 险资每日真实买卖 / L2-B 固收+赎回→权益卖盘 / L2-C 每日真实申赎→股票卖盘 / 私募真实仓位 / 政策资金身份 / 机构风险预算 / 历史日内 available_at 快照（Prospective Observatory 范畴）。"纯前瞻积累期"判断相应缩短。

## 二、七个候选仓库（用户提供）

| 仓库 | 内容 | 对 CF 价值 | 初判 |
|---|---|---|---|
| OrangesHuang/Resonance | ETF份额/价格位置/成交额/融资余额五类指标，一键重建全历史，盘中30秒监测 | L1+M+L4 | **最值得研究架构**；但其"国家队归因"违反 CF 行为/身份分离纪律，禁入合同 |
| wwww1998/national-team-etf-flow | 23只核心宽基ETF 份额×净值≈每日净申赎，~3年，每日20:00 Actions 更新，~400 commits | L1 历史 + **PIT 旁证** | Git 历史可能恢复历史抓取时点（第三方观测证据，非官方证明） |
| zxtcc/szse-etf-share | SZSE 官方 `api/report/ShowReport/data?CATALOGID=scsj_fund_jjgm&jjlb=ETF` 原生日期区间（单次≈180天），自动分窗逐日落盘 | L1 历史 | 直接证明深市历史可回补（与 CF-1A SZSE 探测一致） |
| saitoChen/ETF_Database | SSE ETF 份额历史，SQLite，每日20:00 采样 | L1 历史/PIT 参考 | ETF 池较小 |
| WZB1320/A-Shares-data | 北向/两融/龙虎榜/日线持久化表 | M/L3/L4 | **external checksum / gap recovery / schema reference**，非主源 |
| gaaiyun/TradingWorkbench | 三只 ETF 两融回填 ~6 年（1638/1580/1522 条），处理业务日/UTC/周末/来源混用；明确"资金代理不可归因汇金证金险资主力" | M + 工程方法 | **值得 agent 工程审计**（非 README 浅读）；归因纪律与 CF 一致 |
| AFAC-2025/AFAC2025_train_data | `fund_apply_redeem_series.csv` 2024-04-08 起逐日逐基金申购量/赎回量/曝光UV | L2-C/L2-B | **最意外、最值得核查**：若可用则 CF 首次拥有真实"赎回压力"历史样本 |

## 三、CF-HX 四步（用户定义）

1. **CF-HX-1**：审计 7 仓库（优先：Resonance=历史重建方法 / national-team-etf-flow=Git 时点恢复 / AFAC=申赎历史之门）
2. **CF-HX-2**：逐源记录 source / field / start-end / frequency / official vs derived / PIT status / license / **identity attribution risk**
3. **CF-HX-3**：与我们自己的 backfill（data/cf/raw/）做集合与 hash 对账
4. **CF-HX-4**：只把**能证明语义**的数据纳入历史重放

## 四、AFAC 数据八审清单（用户指定，并入前必答）

基金ID是否匿名 / 基金类型是否可识别（能否区分固收+/二级债基/混合）/ 申购赎回单位 / 真实业务数据 vs 脱敏变换 / 基金数量 / 能否映射A股权益暴露 / 数据授权 / 若全匿名仍可用于"赎回动力学前瞻性"研究（服务 L2-B/L2-C 状态机设计）。

## 五、纪律重申（外部数据红线）

- 外部库的"国家队/汇金归因"**不进 CF 合同**（P1 行为/身份分离；TradingWorkbench 同款纪律）
- GitHub 库 README 的"数据不可得"经验**不可信**——Census 必须追到底层官方接口（szse-etf-share 推翻 national-team-position 旧结论的教训）
- 外部数据默认 = external checksum / gap recovery / schema reference / 方法参考；**主数据源仍是官方直连**；纳入历史重放须过 CF-HX-4 语义证明门
