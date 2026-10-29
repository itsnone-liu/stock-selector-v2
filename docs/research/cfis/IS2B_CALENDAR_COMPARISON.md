# IS2B 局部官方日历比较（非全历年交易日历）

## 范围与证据

本实现是独立比较器，不改 `is2b_node_outcomes.py`、源 nodes 或原 outcomes。
**partial calendar not all years**：仅采用上交所 2024 春节局部日历，不能推断 2023 或其他年份的假期，也不将工作日缺数一概当作休市。

- 官方来源：<https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20231226_5733941.shtml>
- 发布日期：2023-12-26。页面内容已由任务提供的 web_fetch 确证。
- 原文春节安排：2/9 至 2/17 休市，2/19 起照常开市；2/18 另列周末休市。
- 标准化为 2024-02-09..2024-02-18 共 **10 天连续休市**，并非只算九天；2/19 不是休市日。
- 机器证据：`calendar_evidence.json`，ID `SSE-20231226-2024-SPRING-FESTIVAL-PARTIAL`。

## 准入及不掩盖守卫

仅原 `status=WEEKLY_GAP` 可重评，其余行原有所有字段逐字段保留（包括原 COMPLETE）。比较器以原函数重新建立保守基线，核对身份、entry、entry_open、entry_week、window_start/end、window_end_date 和 `window_weeks` 一致；不换 entry、不滚动选周、不按 ISO 周数重选 horizon。原 `window_weeks` 按 **`;`** 分隔，必须恰有 horizon 个周。

原状态顺序中 WEEKLY_GAP 位于末尾，可能遮盖前面的失败。因此比较器另外检查：完整窗口、path 周集合不能超出已选周、每周 endpoint 必须存在于原 daily OHLC 且为该周最后观测日、不能是无法证明结束的 cutoff 短周、entry/end 齐全。基线 entry 守卫仍须通过。缺 endpoint、缺 weekly 或右删失不能借日历恢复。

对 path 中相邻日期以及已选 weekly endpoint 中**每一个 >14 自然日间隔**，遍历严格内部日期：周末不需新增节日推断；已有 daily 记录不属缺失；剩余每个未记录工作日都必须位于本地官方闭市证据区间，否则拒绝。此检查同时约束原 INDEX_GAP，不能由最终 WEEKLY_GAP 掩盖它。

本次关键间隔为 W06 的 **2024-02-08 → W08 的 2024-02-23，15 天**。不能仅比较 weekly end：daily 实际包含 2/19..2/23，内部 2/19..2/22 都有真实记录，2/23 为右端点；缺失的内部工作日才全部落在 2/9..2/18。若人为删除 2/20，必须拒绝。若缺口落在 2023，即使可能是假期，也不能用此 2024 证据放行。

通过后只在原 entry..end 的原 OHLC 上重算：return=end close/entry open−1；MAE=min(0,min low/entry open−1)；MFE=max(0,max high/entry open−1)；first5 为首次 close ≥ entry open×1.05 的观测交易日序号（entry=1）。未命中不虚构等待天数，沿用 `NOT_REACHED_RIGHT_CENSORED`。

## 实跑结果

```sh
python scripts/cfis/is2b_calendar_comparison.py
python -m unittest discover -s tests -p 'test_cfis_calendar_comparison.py' -v
python -m unittest discover -s tests -p 'test_cfis_node_outcomes.py' -q
```

33 行：原 COMPLETE=29、WEEKLY_GAP=2、MISSING_ENDPOINT=2；比较后 COMPLETE=31、MISSING_ENDPOINT=2。**仅恢复 2 行**，均为 IS2B-2024-W01 / A，entry=2024-01-08；另外 31 行全部原字段不变。

| horizon（原选周数） | end | observed days | return | MAE | MFE | first5 / hit |
|---|---|---:|---:|---:|---:|---|
| 8 | 2024-03-08 | 39 | 0.00035246527283394613 | -0.1676520910994348 | 0.008979694732394794 | 空 / 0 |
| 12 | 2024-04-03 | 57 | 0.016253084071137236 | -0.1676520910994348 | 0.03708121406779963 | 空 / 0 |

以上为比例而非百分数；return 约 +0.0352465%、+1.6253084%。两者 wait_status 均为 `NOT_REACHED_RIGHT_CENSORED`。本次不声称补全所有年份日历或修复所有缺口。

产物 `data/cfis/is2b_calendar_outcome_comparison.csv` 位于 ignored data 目录；保留原列，数值列表示新结果，附 `old_status/new_status`、原数值 `old_*`、evidence_id 及 comparison_reason。未恢复行 evidence_id 留空，避免暗示该证据适用于它们。

8 项专项测试通过：春节恢复及数值、daily 日期证明与未证明缺口拒绝、2023 不放行、原 COMPLETE 所有字段不变、源输入不变、缺 endpoint 不恢复、被掩盖的 MISSING_WEEKLY 不恢复、不完整窗口不恢复；原 node outcomes 14 项测试也通过。普通 pytest 在收集前遇到环境现有 pandas/numpy ABI 不匹配（`numpy.dtype size changed`），因此使用标准库 unittest 验证，未修改依赖环境。

主会话随后使用隔离入口 `python3 -m pytest --noconftest tests/test_cfis_*.py -q` 完成全部110项CF-IS针对性测试；不表示全库测试通过。上文普通pytest的环境问题未通过修改依赖规避。
