# TDX 自立门户 · 第三方数据源退役决定 + 迁移台账

- 日期：2026-10-21
- 仓库：`/root/project/workspace/stock-selector-v2`
- 决定人：老刘
- 状态：决定已生效；迁移进行中（A 步 qfq 主链 = 首批目标）

---

## 0. 决定记录（正式落地）

**决定**：自 2026-10-21 起，**腾讯 / 新浪 / 东方财富 / akshare(sina) 等第三方行情源在工程链路上全部退役**，
所有 **TDX 通道能快速获取**的工程数据一律改走 TDX 通道。

**依据（老刘原话）**：
> "以前用新浪腾讯东财是因为服务器没法跑 tdx，现在 tdx 通了就全部扔掉，
>  把所有 tdx 可以快速获取的工程数据全部换 tdx 通道。整理整个系统。"
> "把东财新浪腾讯都扔到垃圾箱，连复核都不需要。"

**技术前提（已闭环的事实）**：
1. 老刘逆向的 `tdx-protocol`（realclient/cli.py）可直连真客户端站，栈已从 `/tmp` 迁到 **`/root/tdx-protocol`**（`/tmp` 会被清）。
2. 复权基准 = 客户端仿射 `cat1-affine-c2`，**与真客户端逐 bar 一致 0.00000%** → 本机 `adjust()` 工程零改动。
3. 本机全市场 TDX 数据 `/root/tdx_data/vipdoc`（214k `.day`，新鲜到前一交易日，裸价未复权）。
4. 触发原因：腾讯 web 双域 WAF 曾把本机 IP 全封 → A 步全市场 qfq 无源；TDX 通道打通后该依赖彻底移除。

**不复核原则**：第三方源数据不再用作裁判（已确认新浪事件因子算错、东财 PRETAX_BONUS_RMB 记错、
新浪乘法模型与客户端最大差 51%）。QD 口径只认 `cat1-affine-c2`。

---

## 1. 已交付：TDX 实时行情 drop-in 模块

`src/r2/tdx_quotes.py` —— 替代腾讯 `qt.gtimg.cn` 的统一入口：

```python
from r2.tdx_quotes import quotes, index_pct
q = quotes(['600519', 'sz000001', 'sh000001'])     # {code6: 快照}
pct = index_pct('sh000001')                          # 指数实时涨幅%
```

字段（**同名同义**于旧腾讯解析，调用方零改动）：
`name / price / pct / high / low / last_close / open / ts / turnover_pct / vol / amount`
— 均取 `Session.snapshot()`（op16 批量，含 `servertime`、`turnover_pct`、`capital_source`）。

---

## 2. 已迁移调用点（本批 6 处，全部 py_compile 通过 + 实跑）

| # | 文件 | 原源 | 处置 | 验证 |
|---|------|------|------|------|
| 1 | `src/r2/intraday_scan.py:quotes/idx_pct` | qt.gtimg.cn 实时 | → `tdx_quotes` | SYNTAX_OK，无残留 |
| 2 | `scripts/intraday_p3rank.py:27-51` | qt.gtimg.cn 实时+大盘 | → `tdx_quotes` | SYNTAX_OK，无残留 |
| 3 | `scripts/export_r2_list.py:46-61` | qt.gtimg.cn 名称 | → `tdx_quotes`（名称随快照返回） | SYNTAX_OK |
| 4 | `scripts/export_insup_conf09.py:27-42` | qt.gtimg.cn 名称 | → `tdx_quotes` | SYNTAX_OK |
| 5 | `scripts/live_check_insup09.py:14-31` | qt.gtimg.cn 实时 | → `tdx_quotes` | SYNTAX_OK |
| 6 | `src/r2/ei5_collect.py:quotes()` | qt.gtimg.cn 实时 | → `tdx_quotes`（字段名保持，`amount_wan=amount/1e4`） | SYNTAX_OK |

附带修正：`ei5_collect.check_trading_day()` 原靠腾讯 `f[30]` 的 `YYYYMMDD` 前缀判交易日，
**TDX `servertime` 只有 `HH:MM:SS.sss` 无日期** → 改为**数据新鲜度**判定
（实时快照 `(price, amount)` 与 day 之前最后一根日线 bar 完全相等 = 隔夜冻结 = 非交易日；
用 sh600519 而非指数，因指数日线解析异常）。实跑：
```
check_trading_day('2026-10-21') -> (True,  'tdx:15:16:55.392 px=1309.69/1331.88 amt=4403823104.0/4525399040.0 prev_bar=2026-10-20')
```
溯源字段同步更新：`'tencent:ifzq.minute+qt.gtimg'` → `'tdx:snapshot+ifzq.minute'`。

---

## 3. 待迁移台账（活链路，按优先级）

| P | 文件:行 | 现源 | 目标 TDX 能力 | 备注 |
|---|---------|------|---------------|------|
| **P0** | `src/r2/daily_price_update.py:19-21` | 腾讯 fqkline（A 步 qfq 主链） | `tdx_client.qfq_daily()`（cat1-affine-c2） | ✅ **已完成 2026-10-21**（见 §7）；默认 `--source tdx`，`--source tencent` 应急回退 |
| **P0** | `src/r2/exdiv_refetch.py:12` | 腾讯 fqkline ×3 域 | `xdxr_batch()` + `qfq_daily()` | ✅ **已完成 2026-10-21**：`refetch_tdx()`，默认 `--source tdx`（见 §7.4） |
| **P1** | `src/stock_selector/data/realtime.py:102` | `qt.gtimg.cn` | `tdx_quotes.quotes()` | ✅ **生产链已是 TDX**：`pipeline.py` 全部调 `TdxQuoteProvider`（7709 分时）；`TencentQuoteProvider` 仅 `tests/` 引用，留作应急回退 |
| **P1** | `scripts/fetch_names.py:19` | `qt.gtimg.cn` | `tdx_client.names(market, date)` 或 `tdx_quotes` | ✅ **已完成 2026-10-21**：改走 `tdx_quotes.names_map()`（190/190 名称 0.1s，diff=0）；`--source tencent` 回退 |
| **P1** | `src/capital_data/market_daily_ext.py:12,38` | akshare `stock_zh_a_daily(sina)` | `Session.daily()`（裸价+amount，复权由 adjust 处理） | CL 链 amount/turnover 扩展列 |
| **P2** | `src/capital_data/ownership_margin.py:8` | akshare | ⚠️ TDX 无直接对应（融资融券/股东户数） | **保留为显式缺口**，需另证 op 或接受保留 |
| — | `scripts/cf/backfill_official.py:131`、`scripts/cf/release_time_probe.py:105` | akshare | 不迁移 | CF 研究/官方回填资产，只读可复现性 |
| — | `output/research/**`、`captures/**`、`config/certified_*.json` | 三方源字样 | **不动** | 冻结研究资产（可复现性），仅历史引用 |

---

## 4. 已确认缺口（需新增 TDX 协议能力，不在"快速获取"范围）

| 缺口 | 现状 | 影响 | 处置建议 |
|------|------|------|----------|
| **分时数据** | `ei5_collect.py:137` 仍走 `web.ifzq.gtimg.cn/.../minute/query` | EI-5P `window` 阶段盘中形态依赖分时 | 需在 `tdx_client` 自研 op（分时接口，候选 0x0FB4）；**pytdx 路线已证伪**（见下） |
| **指数日线** | `Session.daily(1,'000001')` 解析出垃圾：`date='5616-57-86'`、`volume=1.9e47`、`amount=4.7e-36`（同一 op 对股票 600519 完全正常） | 任何用指数日线的链路（市场状态/大盘）不可用 | P1：按指数 opcode/记录布局修 `daily()`；在修好前**不要用 TDX 指数日线** |

**pytdx 路线证伪记录**（不要重走）：
本机 `.venv` 内 pytdx 可 `connect()` 这些站，但 `get_minute_time_data` 返回跨股票雷同的垃圾
（600519 → 0.01/0.49/1.06；sz000001 → 0.0/0.48/0.97），`get_security_bars` 各 category 全 `None`
→ **pytdx 与老刘逆向的"真客户端"站不兼容**（bootstrap/记录布局不同）。分时只能自研 op。

---

## 5. 执行顺序（下一步）

1. ✅ **P0-A 步**：`daily_price_update.py` 已切 TDX 默认（§7.1）。
2. ✅ **P0 除权**：`exdiv_refetch.py` 已切 TDX 默认（§7.4）。
3. ✅ **P1 实时/名称**：`realtime.py`（生产链早已 TDX）、`fetch_names.py` 已迁（§7.5）。
4. ⬜ **P1 `market_daily_ext.py`**：akshare/sina → `Session.daily()`（裸价+amount）。
5. ⬜ **P1 指数日线 bug**：修 `Session.daily` 指数分支（§4）。
6. ⬜ **缺口**：分时 op 自研（EI-5P window 阶段）、两融/股东（§4）。

## 6. 验收纪律

- 每个调用点：`py_compile` + 实跑 + `grep` 确认无残留旧源调用。
- 不再做与第三方源的"对拍"（已退役，不作裁判）；只与**真客户端** `/root/tdx-protocol` 对拍。
- 冻结研究资产（`output/research/**`、`captures/**`、`data/**`）一律不动。
---

## 7. P0/P1 迁移执行记录（2026-10-21 晚）

### 7.0 复权口径定案（老刘 2026-10-21 原话）

> "复权的问题，不用纠结前后计算影响实际涨跌判断，只要涨跌大趋势不变就行。凡是有个别计算
> 无法精确的问题，都可以直接用现价处理，所有可能产生的分析错误我都可以人工判断。"

落地为三条闸门规则（`daily_price_update.py` 与 `exdiv_refetch.py` 同口径）：

1. **重叠段裸价（unadj）**：必须严格一致（价严格、量 ±1 手容差）——这是硬 ground truth，不退让。
2. **复权接缝（qfq seam）**：**不阻塞写入**。差 0.00~0.93% 级别标记 `updated_seam` 照写。
3. **个别事件算不准**（类别 2 配股 / 15 除权，客户端刻意 fail-closed）：**退化用现价**
   （qfq 整段 = 裸价），状态 `updated_rawfallback`；量单位判断不出时兜底按「手」并标 `volguess`。

### 7.1 t5a：`daily_price_update.py`（A 步 qfq 主链）✅

改动：新增 `tdx_seg()` / `_rowmatch()`；`complete_history` 硬编码 False 的闸门改为**窗口覆盖度**
（`returned_count<2`）；volume 单位自校准 ±1 手；`--source tdx` 为默认、`--source tencent` 保留回退；
TDX 单连接无 HTTP 限流 → `sleep(0.15)` 改 `sleep(0)`。

**8 票等价性**（`/tmp/dup_test/verify_tdx_equiv.py`）：5 票 `updated`（10-19 补入行与腾讯时代原行逐字段全等）、
2 票 `updated_seam`（601398/600125）、1 票 `daily baseline unavailable`（603603 真无数据）。

**250 票沙盘复测**（`/tmp/dup_test/seam_and_shard.py`，573ms/票 → 全市场约 48min）：

| 状态 | 数量 | 占比 |
|---|---|---|
| `updated` | 232 | 92.8% |
| `updated_rawfallback` | 6 | 2.4% |
| `updated_seam` | 5 | 2.0% |
| `daily baseline unavailable` | 7 | 2.8% |
| `volume_unit_unknown` | 0 | — |
| `overlap_qfq_mismatch` | 0 | — |

有效写入 243/250 = **97.2%**；`mismatch` 列表现仅含 `updated_seam` / `updated_rawfallback` /
真失败三类，可直接喂 `exdiv_refetch`。

### 7.2 t5b：`exdiv_refetch.py`（除权整段重拉）✅

改动：新增 `refetch_tdx()`（TDX 全量 unadj+qfq 重建）+ `--source tdx|tencent`（默认 tdx）；
check1 改容差比较（价严格/量±1）；check2（vs 本机 TDX 镜像）由阻塞改为**告警**（>20% 分歧才 abort
`mirror_fork`）；**历史起点下界=原文件首日**（首版 `count=len+60` 会把历史每天前扩 60 根，已修）。

沙盘验证 5 票（`/tmp/dup_test/verify_exdiv_tdx.py`，拷贝到 `/tmp/exdiv_sandbox`，真库未动）：

| 代码 | 行数 | 重叠 unadj 价差分 | 状态 |
|---|---|---|---|
| 600125 | 1396→1403 | 0 | ok |
| 601398 | 1401→1403 | 0 | ok |
| 000691 | 1394→1395 | 0 | ok（rawfallback） |
| 002594 | 1401→1403 | 0 | ok |
| 600519 | 1401→1403 | 0 | ok |

耗时 ~1.0s/票，备份写 `exdiv_backup/`。**注意**：rawfallback 票（类别2/15）的 qfq **整段等于裸价**
（000691 样例 7.205→9.300），历史除权跳空保留 —— 属口径 3 的预期结果，可用代码清单见跑批输出。

### 7.3 t5c：`realtime.py` / `fetch_names.py` ✅

- `realtime.py`：**生产链早已是 TDX**（`pipeline.py:137/155/243` 全部 `TdxQuoteProvider`，7709 分时）；
  `TencentQuoteProvider` 仅 `tests/test_realtime.py`、`tests/test_spec_semantics_t2.py` 引用 → 留作回退。
- `fetch_names.py`：改走 `r2.tdx_quotes.names_map()`（一次性 sh+sz 全表 5.2 万行，落盘缓存
  `data/r2/tdx_names/names_<ymd>.json`）；`--source tencent` 保留老链路。
  端到端 2026-10-08：**190/190 名称，0.1s（缓存命中），md diff = 0**。
  与腾讯交叉核对（10-19 池 190 票）：一致率仅差 **-U/-W 后缀与全角空格**（如 优刻得 vs 优刻得-W）；
  **10 票无 TDX 名称**（000040/600696/601059/000666/000976/002699/300356/600213/600705/600811
  —— 均为退市/停牌股，活跃名称表不含）→ md 保持 `—`（不模拟）。

### 7.4 下一批（未开工）

- `market_daily_ext.py`（akshare/sina → `Session.daily()`）
- `Session.daily` 指数分支 bug（修好前禁用 TDX 指数日线）
- 分时 op 自研（EI-5P window 阶段依赖）、两融/股东户数（显式缺口）

## 8. 分时线（1m）现状 —— EI-5P 窗口阶段断源（2026-10-21 实测）

### 8.1 故障事实
- 今日 10:01/10:36 EI-5P 窗口采集**实际失败**：`data/r2/ei5/features/ei5_features_20261021.jsonl` 仅 135KB（平日 274KB），manifest 记 `HTTPError: HTTP 501 Not Implemented`，`source=tencent`，`n_bars=0`。
- 腾讯 ifzq 分时端点已死（同 A 步 fqkline 的 WAF 命运）。→ 窗口特征（PE1/PE2/PE3、峰后缩量、时间到峰）全靠逐分钟序列，**快照替代不了**。

### 8.2 好消息：op4045 period=0x0007 的 1m 请求**在本机 48 主机池可用**
- `python3 lab/tdx_cli.py 000001 --period 1m` → 1000 根/票 · 0.4s · 6 个站点（含真客户端站 175.178.112.197）均返回同构数据。格式/解析已校验，非 pytdx 垃圾。
- 本地 `vipdoc/*/minline/` 目前**为空**（minline 目录 mtime 10-21 18:01）。

### 8.3 ✅ 更正（10-21 晚复核）：**游标能滑，能取到当日** —— 上一版"冻结窗口/游标死值"结论作废
- `lab/tdx_op11_minimal_cli.py` 的 `CURSOR_MINUTE`（`0x01352764`）只是**旧锚点**，不是死值。**c1 小步长递增 → 窗口整体前移**：
  | c1 | 窗口（交易日） |
  |---|---|
  | 旧锚 +0 | 2026-07-08 ~ 07-13（4 日，陈旧） |
  | 旧锚 +300 | 2026-10-08 ~ 10-13 |
  | 旧锚 +305 | 2026-10-13 ~ 10-16 |
  | **旧锚 +313** | **2026-10-19 ~ 10-21（当日）** |
- **头游标实测**：c1 = 旧锚+313 = `20260509` → 单票恰好 **240 根 = marker 46077（2026-10-21）分钟 571~900（09:31~15:00）**；+314 起返空 ⇒ 头在 313。
- **收盘价与本地日线分毫不差**（今日）：000001 **11.41**｜000002 3.46｜300750 227.90｜002594 80.70｜600519 1309.69。沪市票 market 字节须非 0（`\x00\x00`→0 根，`\x01\x00` 正常）。
- **站点无关**：123.60.84.66 / 123.60.73.44 / 124.70.133.119 三站在 head 游标下均返回同一根当日 240 根。
- **标定成本**：c1 ≈ **+3/自然日**推进，`ce` 控根数（`cs=+300, ce=+315` → 1000 根 / 5 个交易日，末段 40 根）。每天 ±10 小范围扫即可重标定。
- 旧扫描（`/tmp/dup_test/cursor_scan.py` 8 组）为何误判：只放大 `c2`、只做 `c1` 大跳（0x10000），**没测小步长前移**。

### 8.4 路线（更新）
| # | 路线 | 状态 |
|---|---|---|
| A | 自研 1m 取数 + 头游标自动标定，接 `ei5_collect` 主源（腾讯降应急回退） | ✅ **可行性已验证**（见 8.3）；工程活 = 寻头 + 批量（1036 票并发） |
| B | `op1721` 拉服务端 `minline/*.lc1` | 冗余，可搁置 |
| C | 东财 1min 应急 | **不再需要**（TDX 已够用） |
| ⏳ | 盘中可用性（10:01 是否已有当日未完成窗口） | **待明早 10:01 现场验证** —— 决定 EI-5P window 阶段能否一步切完 |

> 今日（10-21）窗口数据仍追不回（收盘后才打通），但**从明早起分时不再依赖腾讯**。
