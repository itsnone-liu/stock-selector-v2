# CF-1A Source/PIT Closure — v1.0（字段级启用裁决）

*Date:* 2026-10-16

*Authority:* 用户裁决：吸收七库审计意见，缩短 CF 数据启用时间；不再以所有字段发布时间精确闭合为全局启动门。

*Status:* **CLOSED FOR FIELD-LEVEL ACTIVATION**

## 1. 闭合裁决

CF-1A 从“整批数据全部完成发布时间证明后才能启动”改为**字段级 available_at 门控**：

1. Historical Replay 可立即使用已经落盘并按交易日标记的官方历史数据；只做状态覆盖、缺失、量纲、持续性和 PIT-style 重放，不看未来收益。
2. Prospective Shadow 对每个字段采用已知的最保守可用时点；字段尚未发布时写 `NOT_YET_OBSERVABLE`。
3. 一个字段或原子不可见，只关闭该原子当日输出，不阻塞其他原子和 Capital Weather 并排日报。
4. 首值与终值修订统计继续前瞻积累，属于 source-quality 监控，不再是 L1/M/L4 历史重放的全局 blocker。
5. G1–G8 保持；ETF 折算中和 G9 仍是硬门，未验证的机械变化禁止进入 L1 状态。

## 2. 字段启用表

| 原子/字段 | 历史覆盖 | 历史重放 | Prospective available_at v1 | 缺失处置 |
|---|---:|---|---|---|
| SSE ETF 份额 | 2012+ | ENABLED | T+1 保守口径 | L1 当日 `NOT_YET_OBSERVABLE` |
| SZSE ETF 份额 | 2016-12+ | ENABLED | T+1 保守口径 | 同上 |
| SSE 两融汇总 | 2018+ | ENABLED | T+1 保守口径 | M 当日 fail-closed |
| SZSE 两融汇总 | 2018+ | ENABLED | T+1 保守口径 | M 当日 fail-closed |
| TDX 880005 上涨家数/成交额 | 2021-08+ | ENABLED | T 日晚间本地更新后 | L4 当日 fail-closed |
| TDX 880006 涨停家数 | 2021-08+ | ENABLED | T 日晚间本地更新后 | L4 当日 fail-closed |
| 乐咕当日快照 | 当日 | 禁作历史输入 | 15:00 后交叉哨 | 不影响状态 |
| 东财涨停池 | 约 30 日 | 禁作历史输入 | 当日观察增强 | 不影响状态 |
| 下跌家数 | 未定位 | v1 不依赖 | — | 不构造替代值 |

采用 T+1 是保守决策时点，不声称接口一定到 T+1 才发布。随着 prospective 样本增加，可只提前单字段 available_at，不回写历史状态阈值。

## 3. 四个必答问题

1. **T 日数据何时首次可知？** ETF/两融 v1 统一按 T+1 决策可用；TDX 880 按 T 晚本地更新后可用。精确分钟继续观察。
2. **首次值与最终值差多少？** 当前样本不足以估计稳定分布，因此 v1 不使用 T 日 preliminary 值；只消费保守时点版本。
3. **修订是否有系统方向？** 尚无足够 prospective 样本，不下结论；记录为质量监控字段。
4. **哪些字段只能 T+1 进入决策？** v1 中双所 ETF 份额和双所两融全部按 T+1；L4 TDX 880 可在 T 晚进入。

## 4. 数据底座实测

- SSE ETF：3587 个数据日，首日 2012-01-04，最新 2026-10-15。
- SZSE ETF：2016-12+ 区间快照。
- SSE 两融：修复长区间接口 2000 行静默上限，改为按年分段抓取。
- SZSE 两融：2129 个数据日，2018-01-02 至 2026-10-15。
- L4：TDX 880005/880006 共 1260 个共同数据日，最新 2026-10-16。

## 5. 七库意见的正式吸收

- 外部库仅用于证据、数值对账和工程思想，不导入“国家队/主力”等身份归因。
- L1/M/L4 历史能力均为强，可立即回放。
- Historical Replay 与 Prospective Shadow 双轨并跑、互不改规则。
- ETF 份额机械折算必须中和；未通过 G9 的日期不能输出 L1 状态。
- AFAC 只作 mechanism-discovery sample，不作为全市场校准样本。

## 6. 关闭项与继续监控项

CF-1A 对启动门正式关闭。以下降为非阻塞 source-quality backlog：

- 更多交易日的首次发布时间分布；
- preliminary→final 修订幅度和方向；
- SZSE 接口偶发 reset 的可用率；
- L4 交叉哨长期偏差。

任何监控异常只影响对应字段/原子，除非发现日期串线、未来数据或 silent corruption，才升级为全局 P0。
