# ETF 日度份额免费源验证（P0 重跑，2026-09-15 晚实测）

**背景**：此前判断"ETF 日度份额无免费/低成本来源"已过时。本轮在本机实测，
沪深交易所官方均免费提供逐日 ETF 总份额，**P0 缺口可以直接关闭，无需购买
Tushare 8000积分 / JQData / 商业终端**。

## 实测结果（本机可达性 ✓）

### 1. 上交所官方（免费，逐日快照，T+1 发布）
- akshare `fund_etf_scale_sse(date="20260914")` → 907 只沪市 ETF 全量
- 字段：基金代码/简称/ETF类型/统计日期/**基金份额（份）**（510300=234.03亿份）
- 任意历史日期可查（逐日快照，非区间）；**当日数据当晚清算后才出**
  （实测 09-15 21:00 仍无 09-15 数据，09-14 正常）
- 底层：`query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=...`
  （需 Referer: sse.com.cn + 浏览器 UA）

### 2. 深交所官方（免费，区间查询，支持历史回补）
- akshare `fund_scale_daily_szse(start_date, end_date, symbol="ETF")`
  → 官方 xlsx，字段"**基金规模(份)**"=逐日份额（159915=197.78亿份）
- 日期区间查询，**单次≤6个月**（更长返回空表，分段即可）；2024-06 深史实测可取
- 底层：`szse.cn/api/report/ShowReport/data?SHOWTYPE=xlsx&CATALOGID=scsj_fund_jjgm`
  （需 Referer + UA；偶发连接重置，重试即过）
- 当日列表页（JSON，CATALOGID=1945）也可用，但那是"当前规模(万元)"口径，要份额用上面的 xlsx

### 3. 聚宽 JQData `finance.FUND_SHARE_DAILY`（未测）
本机无账号。官方双源已够，不再必需；如将来要第三方交叉验证再测权限。

### 4. Tushare `etf_share_size`（8000积分，未买）
**结论：可以不买。** 其价值仅剩"份额+NAV+收盘价合并好的表"，省聚合代码；
官方双源 + 现有东财/新浪行情 NAV 已能覆盖。

## 建议落库 schema（capital-observer ETF 通道）

```
etf_code | trade_date | total_share | share_change | nav | close |
estimated_net_flow | source | quality_status
```
- `share_change = S_t - S_{t-1}`（同一 source 内差分，避免跨源口径跳变）
- `estimated_net_flow ≈ share_change × nav_t`
- `source ∈ {sse_official, szse_official}`；`quality_status` 记录清算延迟/缺口

## 证据等级判定（对齐决策系统蓝图）

| 层 | 内容 | 可得时点 |
|---|---|---|
| **事实层** | 交易所官方份额 Δ | **T+1 早**（T 晚清算后发布）——无法盘中当日可得 |
| 基于事实的估算 | Δ份额 × NAV | T+1 |
| 代理层 | 东财/新浪盘中资金流 | 盘中实时 |

→ 盘中决策（14:45 主决策）只能用代理层 + T-1 官方份额事实；
**15:05 复核与次日 09:25 检查点**才接入 T-1 官方份额 Δ。
"份额变化=事实层"成立，但它的 PIT 时点是隔日的，不能冒充当日盘中事实。

## 复现片段

```python
import akshare as ak
# 沪市：逐日快照
sh = ak.fund_etf_scale_sse(date="20260914")          # 907行
# 深市：区间（≤6个月/次，历史回补分段）
sz = ak.fund_scale_daily_szse(start_date="20260914", end_date="20260914")  # 733行/日
```

环境：本机 venv akshare==1.18.56（已装）。SZSE 偶发 ConnectionReset→重试；
SSE 当日未清算时返回空（按 KeyError 处理，降级取最近可得日）。

## 落地状态（2026-09-15）

**已在 capital-observer 上线**（commit 见该仓库）：

- 采集：`ingestion/adapters/etf_share.py`（SSE 逐日快照 + SZSE 区间 xlsx，
  分段≤150天，`\x00` 分段分隔——CSV 含换行绝不能按 `\n` 拼拆，教训见下）
- 入库：`fact_observation`，metric=`etf_total_shares`，unit=shares，
  source_id=`sse.etf_share` / `szse.etf_share`；首跑 2026-09-03..14 双所 8 交易日
  ~1.3万条事实（SSE ~903只/日，SZSE ~730只/日）
- 刷新：`scripts/refresh.py` 3.5 步增量道（`--skip-etf` 跳过，
  `--etf-backfill=N` 无历史时回看 N 天）
- API：`GET /api/v1/etf/shares?code=510300&days=30` → 全序列同源差分后截窗，
  `estimated_net_flow=Δ×当日净值`（净值缺失不外推，当前仅首批15只有nav）
- 消费：v2 `decide` 默认自动拉 `/api/v1/context`（板块流proxy + 两融fact +
  宽基ETF份额fact 三通道规则化 → supportive/neutral/divergent/unknown）

**踩坑（写入长期教训）**：多段 CSV 用 `"\n".join` 再 `split("\n")` 会把每行当独立
CSV：每帧首行数据被当表头 → 几千个互异列名的帧 concat 成 帧数×列数 爆炸矩阵，
parse 假死（CPU 满转无输出）。分段必须用不出现在数据里的分隔符（`\x00`）。
