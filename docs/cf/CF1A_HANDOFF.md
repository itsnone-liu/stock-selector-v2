# CF-1A 交接说明（goal 轮次耗尽时的自动化状态与续作路径）

*写入:* 2026-10-15 23:54（goal round 12/12）· *续作时点:* 2026-10-16 任意时点

## 一、已完成（commits 链）

| commit | 内容 |
|---|---|
| 27bce62+cee139a | CF-0 合同冻结（v1）+ 源文档入库 |
| 4e0386c | CF-1 GO 裁决落盘 + 合同 v2 + CF-1A spec |
| 70006d9/d3c83ba | CF-1A 晚间探测两批（静态项全部定案） |
| d07a9e6 | CF1A_CLOSURE_REPORT v0.7（逐传感器裁决表） |
| 660836d | 采样脚本 + G3 初检通过 + CF1B spec 框架 |
| a88697d/fix | backfill 脚本 + 空快速通道修复 |
| 375753c | L1 观测池 v1（七指数族聚合口径） |
| 71fe9d4/f43f974 | 采样调度器 + 覆盖统计 + 证据汇总脚本 |

**CF-1A 静态项 100% 完成**：官方源身份/深度/单位/断点/标签口径/清盘行为/880 定名（880006=涨停家数；下跌家数 UNLOCATED）/L1 观测池/L4 输入集草案。唯一缺口=发布时点跨日实测+修订复查（自动化进行中）。

## 二、运行中自动化（不依赖任何 session）

| 进程 | 日志 | 计划 |
|---|---|---|
| backfill_official.py | /tmp/cf_backfill3.log | 4 模块（SSE ETF 逐日/SSE 两融区间/SZSE ETF 区间/SZSE 两融逐日），~02:30 完成 |
| sampling_scheduler.py | /tmp/cf_sampler.log | 10-16 五时点自动采样（08:30 两融 T+1 定案 / 11:00 / 14:30 / 15:30 / 20:05 含修订复查）→ docs/cf/cf1a_probes/release_time/*.json |

## 三、明日续作步骤（任意时点，按序）

1. `python3 scripts/cf/coverage_report.py`（backfill 完成后）→ 覆盖统计定稿
2. 20:05 后：`python3 scripts/cf/assemble_closure.py` → closure_evidence.md（发布时点结论+修订 diff 自动生成）
3. 人工裁决补写：ETF same-day 结论定 SUPPORTED-with-lag(≤T晚) 或 same-day-intraday；两融 available_at 定案（T+1 晨？）
4. CF1A_CLOSURE_REPORT.md v0.7 → v1.0 闭合（L4 输入集正式冻结）
5. **呈用户确认**（含 CF-1B spec 的 L4 三项取舍：下跌家数不进 v1 / 回放 2021-08+ / 东财池仅当日哨）
6. 用户确认后 CF-1B 启动：spec 已备（CF1B_SPEC_DRAFT.md），阈值 [TBD-post-CF1A] 处填预注册值，数据底座已在 data/cf/raw/

## 四、纪律红线（延续）

- CF-1B 任何状态赋值在 CF-1A 闭合+用户确认前禁止
- G4-G7（Atom-Only/无未来 outcome/fail-closed/禁聚合）+ G8（不碰 OOS-B）+ backfill 白名单
- 发布时点不满足 available_at≤decision_time → NOT_YET_OBSERVABLE，禁回填
