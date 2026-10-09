# EI-5P：候选触发式前瞻采集（prospective）— 预注册规格

> 状态：**PREREGISTERED**（2026-10-09 冻结）
> 裁定来源：老刘 2026-10-09 口径 —— 「从今天开始，只做候选票，只做竞价到 10:00」
> 本卡片**只做数据采集，不做策略研究**。数据冻结先于任何研究。

## 卡片（EI 模板）

```
idea_id: EI-5P
source: S006 竞价/分时构造（外部思想接口层 EI-5）
source_formula: 竞价缺口 + 开盘30分钟价量效率（PE1/PE2/PE3）
target_decision: DIAGNOSTIC（暂）；唯一候选目标是 TIMING / Activation，非 WHEN-gate
mechanism: 候选票在 T 日开盘 30 分钟内的「推进效率 + 回撤缩量」是否携带 EOD 日线不含的增量信息
new_information: true（EOD 链路完全不含盘中分钟价量）
existing_baseline: 现有 T3(量价) + Cost Support(位置) 只到日线粒度；候选池内「真启动 vs 普通震荡」
  无法区分。EI-5P 只补这一处新信息域，不改任何现有 gate。
incremental_question: 在候选池内，PE1/PE2/PE3 + auction_gap 对 5d 前瞻收益是否有单调、可解释的增量？
frozen_inputs:
  - cohort: T-1 收盘 current_scan_<T-1>.json，pool=candidates（与 intraday_scan.py 同口径）
  - window: 09:25 竞价 + 09:30–10:00（共 ≤31 个 1 分钟点）
  - source: tencent web.ifzq.gtimg.cn/appstock/app/minute/query + qt.gtimg.cn（快照）
outcomes: 不在此卡片定义（本卡片不研究）。研究卡片待 EI-5F2 通过后另立。
promotion_rule: EI-5F2 覆盖率 ≥95% 且竞价字段全可解析 且失败率 <2% → 进入前瞻研究阶段（EI-5P-R）
stop_rule: 60 个交易日后若 PE3 分位对 5d 前瞻收益无单调或 |t|<2 → ARCHIVE，不救
status: PREREGISTERED
```

## 一、口径（照令执行，不得擅改）

| 项 | 值 | 说明 |
|---|---|---|
| 起点 | **T = 2026-10-09** | 不回填历史 |
| 对象 | **只做候选票** | 复用 `intraday_scan.py --pool candidates` 选池逻辑，零口径分歧 |
| 窗口 | **竞价 + 到 10:00** | 09:25 竞价快照 + 09:30–10:00 每分钟 |
| 不做 | L2 / 逐笔 / 十档 / order flow / 全市场分时 / 多年历史采购 / 指标矿场 | |
| 不动 | **现有 EOD 日线链路（C→E→F）一行不改** | |

### 候选池口径（与生产同源）
```python
keep = {'CONFIRM_CANDIDATE','BUILD','WATCH'}
cohort = [c for c in cards
          if c['decision']['decision_tier'] in keep
          or c['capital_support']['support_state'] in ('IN_SUPPORT','UNDERCUT_TEST')]
```
实测：T-1=10-08 → cohort = **1036 只**（CONFIRM_CANDIDATE 85 / WATCH 416 / NO_BUILD 750 / EXIT 2363 / RISK_HOLD 105 为全表 tier）。

## 二、数据源（实测确认，2026-10-09 21:4x）

| 用途 | 路由 | 实测 |
|---|---|---|
| 1 分钟点 | `https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sz000001` | 可用。当日 267 点（0930→1530），`data.<code>.data.date='20261009'`。每点 `"HHMM 价 累计量(手) 累计额(元)"` |
| 竞价/快照 | `http://qt.gtimg.cn/q=sh600000,sz000001,...`（60 只/请求，GBK） | 可用。f[3]现价 f[4]昨收 f[5]今开(=竞价价) f[6]量(手) f[37]额(万元) |
| 20 日均量额 | `/root/tdx_data/vipdoc/{sh,sz,bj}/lday/*.day` | 裸价未复权；volume 单位=手；amount 单位=元 |
| ~~1min OHLC 其他源~~ | EMI push2his klt=1 / 腾讯 mkline / fqkline | **全部不可用**（EM 超时、mkline 301、fqkline param error） |

### ⚠️ 已知数据缺口（必须记录，不得掩盖）
腾讯分钟接口**只给每分钟收盘价 + 累计量额**，**无每分钟 OHLC**。
- ⇒ PE1/PE2/PE3（位移/额、位移/量、回撤额/上涨额）**全部可算**，因为它们只用收盘价差分 + 量额差分。
- ⇒ 窗口内 high/low 只能用「1 分钟收盘价的最大/最小值」代理，字段名带 `_cproxy` 后缀，不得当真实高低点用。
- ⇒ MFE/MAE 一律从日线标签取，不用分钟数据。

## 三、采集时点（T 日）

| 时点 | 动作 | 产出 |
|---|---|---|
| T-1 18:10 | 现有 EOD（**不动**） | `current_scan_<T-1>.json` 冻结 cohort |
| T 09:28 | 竞价快照（qt.gtimg 批量；09:25 撮合后 09:25–09:29 数据不变） | `stage=auction` raw |
| T 10:01 | 拉 ≤31 个 1min 点 → 差分 → 特征 → 封存（等 1000 点走完再取，避免半根） | `stage=window` raw + features |
| T 19:00 | TDX 日线补 +1/+5/+10/+20d 标签 | `stage=labels`（每日回补） |

**交易日闸门**：`check_trading_day()` 用 `qt.gtimg sh000001` 的 f[30] 时间戳判 T 是否开盘；非交易日直接 `skipped=NOT_TRADING_DAY` 退出，不写文件。周末由 cron `1-5` 挡，节假日由闸门挡。

**已上线 cron**（`scripts/ei5_cron.sh`，2026-10-09 启用；只碰 `data/r2/ei5/`，不碰 EOD）：
```
28 9 * * 1-5  scripts/ei5_cron.sh auction
 1 10 * * 1-5 scripts/ei5_cron.sh window
 0 19 * * 1-5 scripts/ei5_cron.sh labels
```
周一 2026-10-12 起自动跑。

**周一额外校验（一次性）**：收盘后跑 `--stage backfill --day 2026-10-12`，与盘中 `stage=window` 落地的同一批码逐字段比对；差异即为盘中取数时点误差（尤其 1000 点是否半根），有差异就以回补口径为准并修时点。

## 四、存储布局

```
data/r2/ei5/raw/<YYYY-MM-DD>/<code>.json.zst    # 原文冻结，留 90 天（之后只留 raw_sha256）
data/r2/ei5/features/day=<YYYY-MM-DD>.parquet   # 特征，永久追加（按日一个文件）
data/r2/ei5/labels/ei5_labels.parquet           # 标签，每日回补追加
data/r2/ei5/manifest.jsonl                      # 每 (day,code,stage) 一行：raw_sha256/source/available_at/git_sha
data/r2/ei5/coverage/<YYYY-MM-DD>.json          # 当日覆盖率/失败原因/字节数/耗时
```

**冻结纪律**：特征代码一经跑通即记 git sha 冻结；raw 封存 sha256；后续加字段=新开一列，不改旧列。

**存储实算**（1036 只 × ≤31 点，2026-10-09 实测）：
- raw：**单文件** `raw/<day>_<stage>.jsonl.zst`，1036 只 = **435 KB/天**（未压缩 ~1.5 MB）。按票拆文件会因 4K 块对齐变成 4.1 MB/天，故只留单文件；写入按 code 合并，子集重跑不会截断已有票。90 天 ≈ **40 MB**
- features：1036 行 × 42 列 = **252 KB/天**（parquet），一年 ≈ 64 MB
- manifest/coverage：~400 KB/天
- 合计 **≈ 1.1 MB/天 ≈ 0.4 GB/年**；对照全市场 tick 200 MB/天 → 低约 **200 倍**

## 五、特征定义（冻结 v1）

设竞价点 `bar0`（0930 或 0925），窗口內 `i=1..30`：
```
v_i = cumvol_i - cumvol_{i-1}     # 每分钟量(手)
a_i = cumamt_i - cumamt_{i-1}     # 每分钟额(元)
r_i = p_i / p_{i-1} - 1           # 每分钟收益
disp        = p_last/auction_price - 1        # 窗口位移
amt_ratio   = Σa_i / avg20_amount             # 窗口额比(20日均日额)
vol_ratio   = Σv_i / avg20_volume             # 窗口量比
PE1         = disp / amt_ratio                # 每单位额比的位移效率
PE2         = disp / vol_ratio
PE3         = Σa_i[r_i<0] / Σa_i[r_i>0]       # 回撤额 / 上涨额
auction_gap = auction_price/prev_close - 1
auction_vol_ratio = bar0.cumvol / avg20_volume
range_cproxy      = max(p_i)/min(p_i) - 1
retrace_from_peak = p_last/max(p_i) - 1
time_to_peak_frac = argmax(p_i)/30
tail_vol_ratio    = Σv_i[i>20] / Σv_i[i<=10]
peak_dn_vol_ratio = 峰后量 / 峰前量
```

## 六、门槛与判据

**EI-5F2 门槛**（跑满 5 个交易日）：覆盖率 ≥95%、竞价字段 100% 可解析、失败率 <2% → 进 P；否则先修不研究。

**EI-5P-R 预注册判据**（60 个交易日后，≥3000 观测）：PE3 分位对 5d 前瞻收益单调，top−bottom ≥1.5%，block bootstrap t≥2 → 才谈扩窗/上 tick/买 L2。

**止蚀线**：60 天后无单调或 |t|<2 → ARCHIVE，不救。

## 七、运行

```bash
cd /root/project/workspace/stock-selector-v2
# 手动/回补（T=day，cohort 取 base=前一交易日 scan）
.venv/bin/python src/r2/ei5_collect.py --stage backfill --day 2026-10-09 --base 2026-10-08
# 盘中
.venv/bin/python src/r2/ei5_collect.py --stage auction --day <T>
.venv/bin/python src/r2/ei5_collect.py --stage window  --day <T>
# 标签回补
.venv/bin/python src/r2/ei5_collect.py --stage labels  --day <T>
```

## 八、执行记录

### 2026-10-09 首日回补（T=10-09，cohort=10-08 scan，`pool=candidates`）

| 项 | 实测 |
|---|---|
| cohort | 1036 只（scan cards=3781，tier∈{CONFIRM_CANDIDATE 85, BUILD, WATCH 416} 等） |
| ok / fail | **1036 / 0**，覆盖率 **100%** |
| 1 分钟点数 | 1035 只 = 31 点（0930–1000 全）；1 只 = 1 点（`partial=True`，窗口内基本无量） |
| `src_date` | 1036/1036 = `20261009`（无陈旧数据污染） |
| 20 日均量基线 | 1036/1036 命中 TDX 日线（`has_20d=1`） |
| 耗时 / 体积 | 844 s（串行 0.1 s 节流）/ raw 435 KB |
| 冻结 | raw jsonl.zst 单文件，逐票 sha256 入 manifest；`git_sha=163bf4e` |

**关键特征中位值（10-09 为下跌日，可作合理性对照）**：`auction_gap` 0.00%、`auction_vol_ratio` 0.30%、`disp(-09:30→10:00)` −0.90%、`win_amt_ratio` 26.6%、`PE3`(回撤额/上涨额) 1.40、`tail_vol_ratio` 0.40。
→ 值域与"下跌日、尾段缩量、下跌成交额大于上涨成交额"的直觉一致，特征非垃圾。

### 周一 10-12 第一个真实前瞻日（必须做的一致性校验）

live 采集（09:28 auction / 10:01 window）与收盘后 backfill 同一 T 日，比对同一只票的 `disp / PE1 / PE2 / PE3 / win_amt_ratio`：
- 若 **完全一致** → 说明 10:01 取数不含量能未完的半根，live 链路可用；
- 若 **window 最后一次出现半根偏差** → 把 window 时点后移到 10:01:30 或丢弃 `last_hhmm=1000` 那根。

```bash
# 周一收盘后
.venv/bin/python src/r2/ei5_collect.py --stage backfill --day 2026-10-12   # 覆盖同日的 live 特征
```

**标签不得前视**：`--stage labels` 只用 `day` 之后的 TDX 日线；T 日的 r20 在 T+20 个交易日后才落地，未足期写 NaN。cron 每日 19:00 对最近 26 个自然日滚动补标签。