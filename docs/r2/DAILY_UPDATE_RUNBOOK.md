# 每日更新运行手册（Hermes 执行版）

> 2026-10-08 建立。一条命令跑完当日全链。任何一步失败即停、显式报错、不许静默。
> 仓库：`/root/project/workspace/stock-selector-v2`（git；每日跑完 commit）。

## 0. 前提（每天 18:10 后才能跑）

- 本地 TDX 镜像 `/root/tdx_data/vipdoc/` 已含当日日线（外部进程 18:00 自动同步 zip，如 `20261008.zip`）。
- 验证方式：`sz000001.day` 最后一根的日期 == 今天。编排器会自检，未到位直接退出。

## 1. 一条命令

```bash
cd /root/project/workspace/stock-selector-v2 && \
.venv/bin/python src/r2/daily_update.py --day $(date +%F)
```

步骤（fail-closed 链式，任一失败中止并留下日志）：

| 步 | 内容 | 产物 | 预计耗时 |
|---|---|---|---|
| A | 腾讯 fqkline 增量补日线（append-only，TDX 逐bar校验） | `data/cd/daily_fullmarket/*.json.gz` +30~120min | ≤120min |
| C | 轴滚动：cd1b(L2四轴)→cd45(L1 regime)→cd2bc→cd4v2→cd5a，**历史行 subset 相等性校验，丢行即中止** | `data/cd/sector_axes/*`、l3/l4 | 10-40min |
| E | current_scan 全量重跑（含 regime 五日多数票） | `data/r2/scans/current_scan_<day>.json` | ~15min |
| F | 日报：tier 迁移表 + 固定切片交叉统计 + BROKEN 临界队列 | `data/r2/daily_update/report_<day>.json`（追加 `crossval_history.jsonl`） | <1min |

每步日志：`data/r2/daily_update/step_*.log`；A 的 manifest：`update_<day>.json`。

## 2. 跑完必须人工/上游看的三样东西

1. **`update_<day>.json` 的 stats**：`fetch_fail`、`tdx_mismatch`、`overlap_*_mismatch` 必须≈0；
   `overlap_qfq_mismatch` > 0 = 有除权股，整段 qfq 需重拉（见 §4.3）。
2. **`report_<day>.json` 的 `migrations`**：tier 跳变清单（CONFIRM→EXIT 等是行动信号）。
3. **`broken_queue`**：exit_distance 最小的前 30 只——负值=已越触发线，等 5 日确认即 EXIT。

## 3. 失败恢复

- **某步失败**：修因后单独重跑该步：`--skip A,C` 只跑 E,F（skip 取补集语义：列出要跳过的）。
- **C 报 HISTORY LOST**：轴文件已被构建器重写——`git checkout -- data/cd/sector_axes/` 恢复后排查，严禁带伤继续。
- **2026-10-12 守卫修复一（l3_pool 误报）**：l3_pool 不再走通用 KEYED 检查（旧实现遍历 pools 顶层 dict、比的是快照键存活，当月重键 `2026-10-09→2026-10-12` 每天必误报）。现由 `check_l3_pool()` 专用校验：历史月快照逐字节冻结；当月允许重键+重算；满 65 月窗口仅允许最老端连续顶出且与新月 1:1 配对。真丢历史（丢中间月/改历史月内容/非最老端消失）仍然中止。
- **2026-10-13 守卫修复二（P2，重定基微扰容差）**：exdiv 整段重拉后重建 C，市场/板块层滚动统计把微扰扩散进全部历史行（l2_four_axes 98084 行、l1_market_axes 1143 行；变的仅 mkt_\*/rel_\*_mkt/sector_vw/top5_mean_ret 等 float，n/status/结构不变；p50≈1e-5，绝对上界≈5e-4），逐字节严查误报。现通用路径加容差：指纹（结构+非数值+整数计数，l1 的 b_conc/b_disp/b_part 档位读数除外）严格相等 + float |Δ|≤1e-3 或相对≤1e-2 视为存活。行消失/状态变/计数变/数值大改仍中止。
- **补昨天**：`--day 2026-10-09` 传哪天补哪天；A 是 append-only 幂等的。
- **腾讯限流**（A 大量 fetch_fail）：等 20 分钟重跑 A，已更新的股票自动 skip。

## 4. 已知边界（不要"顺手修"）

1. **TDX 裸价不进成本带**——成本带/支撑只用 daily_fullmarket 的 qfq 列；TDX 只做校验、当日涨跌、停牌识别。
2. **停牌股**：当日无 TDX bar → 交叉统计自动剔除（腾讯 pct=0 教训）。
3. **除权股**（overlap_qfq_mismatch）：腾讯 qfq 会整体重定基，导致 overlap 校验失败被跳过 → 当日该股停在昨日；处理=对清单内股票重拉全量 qfq 段替换（v1 手动，脚本 `daily_price_update.py --day <day> --limit 0` 不覆盖此场景）。
4. **regime**：决策用五日多数票（2026-10-08 冻结），五状态定义不改动。

## 5. 慢频数据（H，不进每日链）

| 项 | 频率 | 方式 |
|---|---|---|
| e5（两融/龙虎榜/大宗） | 每周一 | 用户机器增量包 → `src/capital_data/e5_build_db.py --append`（context 层，滞后无害） |
| 股东户数 holders | 每月 1 号 | `src/capital_data/ownership_margin.py`（4/8/10 月披露高峰必跑） |
| 机构 top10 | 每季度末 | `src/capital_data/institution_classify.py` |
| 新股纳入 | 每月与 holders 同天 | 从 TDX 文件数对齐宇宙，新股满 520 日才进成本带池 |
| market_ext（amount/turnover） | 每周 | `src/capital_data/market_daily_ext.py` 增量（研究面板用，非关键路径） |

## 6. 资源与纪律

- 单进程、流式逐股，峰值内存 ≤2.5G；禁再生成单体大表。
- append-only：历史行永不改写；C 的 subset 校验是硬门。
- 日期键纪律：跨数据集一律 `d.replace('-','')`；月份切片 `[:7]`。
- 每日跑完：`git add -A && git commit -m "daily <day>"`。
- PIT：E5 用 T+1 公布时间；qfq 段随源重定基属数据源特性，不视作改历史。

## 7. 一句话验收

`report_<day>.json` 存在、`n_traded+n_suspended ≈ 卡片数`、`migrations` 可解释、`update_<day>.json` 无非零失败计数 —— 当日闭环。

## Shadow 封存（每晚 F 之后必跑）
.venv/bin/python src/r2/shadow_portfolio.py --day $(date +%F)
三账户 A/B/C + breadth + Q5 + 哈希，逐日累积 attribution。
