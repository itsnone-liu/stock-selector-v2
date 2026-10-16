# TDX 052d 数据源重新审计（2026-10-16）

## 总裁决

TDX 日线、1m、5m 数据可用。此前观察到的分钟 amount/volume 不闭合不是数据口径差异，而是本地 052d 解析器错误地套用了 pytdx 旧版 `get_volume()`。当前主站的两个成交字段应按 IEEE-754 float32 解码。

修正后：

- 日线、1m、5m 的 amount/volume 内部闭合；
- 84 股 2026-10-15 全样本上，TDX 5m 汇总与 TDX 日线及现有 R4 日线 amount 全部精确一致；
- TDX 与现有 R4 的 09:35–10:00 opening amount 中位数完全一致，最大偏差约 0.55%；
- 1m 聚合出的 48 根 5m OHLC 与 TDX 原生 5m 逐根精确一致。

TDX 应按覆盖深度使用，而不是整体接入或整体放弃：

1. 日线：可作为本地 `.day` 的网络补充与完整历史校验；
2. 1m：用于当前盘中 Quote、近端分钟回放、VolumeClock profile、OpeningImpactState 近端/OOS 增量；
3. 5m：用于 R4 OOS-B 日更和近一年回放；
4. 2021–2026 全历史 R4：保留现有已冻结历史数据，因为 TDX 主站分钟保留期有限；
5. 分笔：当前可读，但现有缺口已由 1m/5m 覆盖，不进入主链路，不继续逆向。

## 根因

op052d 每条 bar 尾部两个 4 字节字段为：

```text
volume: f32
amount: f32
```

旧实现将它们当作 u32 后送入 pytdx `get_volume()`。该函数对部分 bit pattern 恰好给出与 float32 相同的数值，因此错误很隐蔽；对另一些 bit pattern 则会静默错解。

真实样本 `601298 / 2026-10-15 09:35`：

```text
raw volume = 0x49a87500
float32     = 1,380,000
旧解码       = 1,380,000     # 偶然一致

raw amount = 0x4b535a65
float32     = 13,851,237
旧解码       = 8,411,749     # 错误
```

09:40 则 volume 字段出错而 amount 恰好一致。这正是此前出现“有些 bar amount 一样，有些 bar volume 一样”的原因。

单位合同：

- amount：元；
- 日线 volume：原始为手，CLI 对外转为股；
- 1m/5m volume：原始已为股；
- 时间：1m 为 `YYYYMMDDHHMM`，每日 240 根（09:31→15:00）；5m 每日 48 根（09:35→15:00）。

## 完整性验证

### 四股跨周期闭合

对 000001、600000、601298、300750 的 2026-10-15：

```text
sum(1m amount) / daily amount = 1.000000
sum(5m amount) / daily amount = 1.000000
sum(1m amount) / sum(5m amount) = 1.000000
```

volume 仅有 float32 舍入级误差。

### 84 股 R4 样本验证

对冻结 84 股样本的 2026-10-15：

| 检查 | 结果 |
|---|---|
| TDX 5m / TDX daily amount | 84/84 精确 1.0 |
| TDX 5m / R4 daily amount | 84/84 精确 1.0 |
| TDX 5m / daily volume | 中位 1.0，最大误差约 0.012% |
| TDX close / R4 close | 84/84 精确一致 |
| 09:35–10:00 opening amount | 中位比值 1.0，最差约 -0.55% |

逐根 5m 与 baostock 可能存在成交归桶边界差异，但全天成交额、成交量和开盘窗口量高度一致。这种差异不构成 TDX 数据不可用；消费层应使用固定源并冻结 bar 边界定义。

## 覆盖深度

活主站实测：

- 1m：约近两个月；
- 5m：约近一年；
- 日线：完整上市历史。

因此 TDX 不能重建 2021–2026 的全部 1m/5m 历史，但能稳定补：

- 当前盘中分钟数据；
- 近端回放；
- OOS-B 每日增量；
- 免费源不可用时的 R4 增量采集。

## 与 stock-selector 的用途映射

### A. 决策系统分钟降级模式

TDX 1m 可直接解锁：

- `quote_from_minutes()` 的真实盘中 Quote；
- 盘中价格、开盘价、累计量、累计额；
- `VolumeClock.profile_v1` 的历史分钟累计量分布；
- 14:45 检查点和有限近端 PIT 回放。

这正是 `docs/MINUTE_DEGRADED_MODE.md` 中原定的升级条件。需要新增网络 1m provider 或将 1m 落盘成现有 `TdxMinuteReader` 可消费的格式。

### B. R4 / OpeningImpactState

TDX 5m 可用于 OOS-B 日更：

- 每日 48 根；
- amount/volume 与日线闭合；
- 09:35–10:00 opening amount 与现有源高度一致；
- 可替代易挂起的 baostock 增量采集，但不改写已冻结历史样本。

正确做法是设置明确切换点并记录 `source_id=tdx_052d_v1`。冻结前历史不重跑，冻结后 OOS-B 可从切换日开始使用 TDX；切换日前后保留一次双源重叠校验。

### C. 日线

网络日线不取代本地 18:00 自动同步的 `.day` 主镜像；它适合：

- 当日完整性校验；
- 缺文件补抓；
- 镜像延迟时的应急备源；
- 远端 Linux 节点无本地 vipdoc 时的纯 Python 数据源。

### D. 分笔

`op 0xfc5` 已可读取，但当前主需求已由 1m/5m 满足。分笔不进入生产，不继续逆向，除非未来有明确的集合竞价/逐笔方向数据缺口。

## 最小接入顺序

1. 合并 tdx-protocol 的 float32 解码修复和离线回归测试；
2. 将 TDX 5m 作为 `cl_r5b_daily_append.py` 的可选增量 provider，保留原 G1：48 bars、Σ5m amount/daily amount∈[0.95,1.05]；
3. 连续若干交易日双源并跑，记录 source_id 和逐日差异，不改历史冻结产物；
4. 新增 TDX 1m provider，接入 `quote_from_minutes`；
5. 用至少 20 个完整日构建 `VolumeClock.profile_v1`；
6. 只有以上通过后，更新 `MINUTE_DEGRADED_MODE.md`，解除“分钟数据不可得”状态。

## 停止边界

不再继续逆：

- 私有账号登录；
- op44d/op44e；
- L2/十档/逐笔委托；
- 分笔历史归档。

现有 TDX 数据已经足够补当前缺口。后续工作应是接入、门禁和监控，不是继续扩大协议面。
