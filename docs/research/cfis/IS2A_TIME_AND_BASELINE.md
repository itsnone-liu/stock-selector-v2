# CF-IS Phase 2A — 时间与基准核验

范围仅 IS-0/IS-1 周表与针对性测试；无新抓取、无全仓审计、无进度文件修改、无 commit/push。以下是本地冻结文件核验，不构成 PIT 或可交易性认证。

## 1. atoms available_at 原样核验

逐行单进程读取 `data/cf/derived/atoms/`，未把值预先变换成日期再作推断：

| 文件 | 行数 | date 范围 | available_at 为 null/缺失 | 实际非空格式 |
|---|---:|---|---:|---|
| l1_history.jsonl | 3595 | 20120104–20261027 | 296 | `20130318+1 conservative` … `20261027+1 conservative` |
| m_history.jsonl | 2137 | 20180102–20261027 | 20 | `20180130+1 conservative` … `20261027+1 conservative` |
| l4_history.jsonl | 1268 | 20210802–20261028 | 60 | `20211103 evening` … `20261028 evening` |

这些是文本代理，不是带时区的实际发布时戳；`+1 conservative` 不能擅自理解为下一交易日开盘可见，也不保证当时版本可恢复。

新增列：
- `available_at_raw`：按源、date 保留原样值（含 null），便于追溯；
- `assessment_at`：观察 ISO 周之后的周一 00:00 Asia/Shanghai，为整周记录的保守评估下限，不是成交时点；
- `usable_at`：已知格式的上界与 assessment 下限取最大。`+1 conservative` 暂按下一**自然日** 23:59:59；`evening` 按当日 23:59:59。缺任何源或任一所用行不明则留空，禁止回填成观察日。此规则是保守代理，不是原始发布凭证；
- `availability_unknown` 与 `timing_scope`：明确未知数及适用边界。

axes 原始收益/广度仅假设日终可评估，缺少发布凭证。`ax_regime` 的档位是历史生成器在 development <=2023-12-31 拟合的 frozen bands，对开发区间有回看，不是逐时点 PIT 标签，不能进入候选交易信号。episodes 使用最终生命周期、terminal 结果，属于回顾性描述；`usable_at` 不覆盖其 PIT 可用性。

**观察周不等于周五可交易。** 后四周收益仅为观察周后的描述性路径，未按真实发布时间/下一可执行开盘重锚，不能称策略收益。

## 2. 历史 axes eq_ret 的真实生成来源

证据是 `scripts/cd45_market_regime.py`，不是 `src/r2/live_market_axis.py`：
1. 逐个读取 `data/cd/daily_fullmarket/*.json.gz`（排除 `_` 开头文件）；
2. `qfq` 行第 2 下标为收盘，`r = closes[i]/closes[i-1]-1`，前收盘 <=0 排除；
3. 对当日可得横截面作 `m = sum(rets)/len(rets)`；
4. `eq_ret = round(m, 8)`。非官方指数、非中位数，股票数与成员可随日变，不保证可交易宇宙/存活偏差/PIT 复权。
5. 完整 axes 还需 ret20d/part/trend，trend 需250观察日，因而起始已截去热身期；冻结文件 1159行，从2022-01-13起。

独立低内存实算核验首日 2022-01-13：逐文件读取，4602只股票，横截面均值 round(8) = **-0.00927559**，与冻结 axes 完全一致。未重建/覆盖原始 axes。周收益应逐日几何复利；不是把日均值求和后 round(2)。现状检查时 IS-0 的 axes 周收益已采用 prod，但空列表得到0，且缺失日被悄悄略过；通用 `agg(sum)` 仍 round(2)。本次消除隐式缺失收益0与求和量化风险；金额/计数 sum 使用 math.fsum，不再做两位截断。

## 3. 修复后的统计边界

- 数值只在展示时格式化；收益内部不 round(2)，拒绝 NaN/Inf。
- 周内任一有观测日期缺 axes/eq_ret，周收益留空；不把剩余几天复利伪装完整周。
- CLI 首尾截断周（start晚于周一或end早于周五）不产完整周收益。没有引入外部交易日历，因此无法证明全源共同缺失的一天不存在；仍属保守可观测周口径。
- 向前路径必须完整4个连续 ISO **日历周**、有全部收益，且首个未来周与观察周相邻，否则剔除。长假整周无记录也算中断，不将“后4条”冒充“后4周”。
- 8周滚动要求8个连续 ISO 日历周、全部收益有效；不足/断档标 `INSUFFICIENT8`，不作CHOP或趋势分类。
- ISO53周用 fromisocalendar 实际周一日期相减；支持闰年和跨年。
- 日期参数同时支持 YYYYMMDD / YYYY-MM-DD，校验真实日期、顺序、空区间；裸输出文件名可用。

全窗口试跑 `2022-01-01..2026-10-28` 输出 `/tmp/cfis_weekly_phase2a_full.csv`，246观察周，3周无完整收益（2022-W01、W02、2026-W44），3周 atoms 代理可用时间未知（2024-W42、2025-W03、2026-W04）。34个支持增强×杠杆收缩观察中，完整后4周可评估20个；不得继续把34个全部当结果样本。

该窗口描述性结果：分化当周有效收益中位 -2.65%，范围 -16.17%..+3.09%，负周81%；完整后4周中位+0.4%，范围-10.0%..+11.2%。共振3周后4周中位+3.6%。8周标签：INSUFFICIENT8=47、CHOP8=59、DOWNTREND8=43、DECLINE8=19、UPTREND8=42、SURGE8=36。既有 IS1 文档的路径样本量、分位数、8周分段占比、最大涨跌案例窗应标 superseded 并重算；这些数字是描述性，不升格为机制证据。

## 4. 真实基准候选与可用范围

**真实指数本地文件可用路径：`docs/phase_i/evidence/market_index_000985.json`**。元数据 `index="000985 CSI All-Share"`, `convention="raw close"`，1280个唯一 trade_date，2020-08-12..2026-04-30。它是中证全指价格序列候选，不是上述等权个股代理，也不是含分红总收益指数。

重要限制：2023-03-31→2023-09-05 存在158天缺口，不能把覆盖范围当连续覆盖；2026-04-30后无数据。可用于有端点、无内部异常断档的子窗口，不得跨缺口计算伪日收益或填补后续。

父任务另有独立 `scripts/cfis/is2a_index_baseline.py` 及 `data/cfis/is2a_index_baseline.csv`，按周端点与<=14天间隔守卫输出197/246周有效基准（其余缺失），本任务未修改该脚本。正式相对收益必须确认同一起点、完整窗口，并明确价格收益而非总收益。

`data/cd/sector_axes/l1_market_axes.json.gz` 仅保留为 **EW observational proxy**；不把它命名为真实指数。`docs/research/strategy_contract/BENCHMARK_SPEC.md` 的个股前视中位数市场基准是另一种定义，不能与日等权复利/官方指数混称。

## 5. 针对性验证

- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest -q tests/test_cfis_weekly.py`：**13 passed**，覆盖精度、空值、NaN、完整4周、缺周、8周不足、ISO53、日期参数、原样时间与CLI聚合。
- 系统 python 常规 pytest 被既有 pandas/numpy ABI 不匹配阻断；`.venv` 正常通过，系统 python `--noconftest` 亦13 passed。没有安装/修改依赖。
- 两脚本顺序单进程运行：2024全年52周、全窗口246周，atlas均成功。结果在 `/tmp`，未覆盖旧 CSV，便于父任务显式重建后续产物。
