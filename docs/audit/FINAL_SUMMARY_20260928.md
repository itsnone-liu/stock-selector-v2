# stock-selector-v2 正式审计 — 最终摘要（T4）

冻结任务书 hash `3ed7f3bc098d`，四阶段 T1→T4 全链完成。
测试命令（全链统一）：`PYTHONPATH=src /root/.hermes/hermes-agent/venv/bin/python3 -m pytest -q --junitxml=<path>`。

## 各阶段 commit 与结果

| 阶段 | 运行 | 审核结果 | 关键 commit（HEAD=通过时远端 tip） |
|---|---|---|---|
| T1 基线与契约 | audit_20260928010142066 / 053052504 | 通过（基线确立） | 基线 451 tests / 0 fail |
| T2 规则与数据语义 | audit_20260928055411432 | **APPROVE** iter 9 | `748d7c9` 未来闸门按完整时间戳+量能回退；`2fdf9fd` 双阳量效率+趋势/底部新鲜度归档；`65d4991` 语义文档；`b6a4dc6` 可执行终验门证据；`346aeb0` 空数据走新鲜度诊断 |
| T3 专项通道与研究边界 | audit_20260928115358315 | **APPROVE** iter 2 | `e779372` 池刷新绑定显式 asof + `--realtime` 守卫；`4f4b5d5` 顺序无关校验 + fixture e2e 入库；`91f2db8b` 最早终止事件语义（延迟刷新竞争） |
| T4 最终回归与交付 | audit_20260928124829807 | 本次 | 本提交（SPEC §9 边界同步 + 本摘要） |

## 修复项汇总（按严重度）

**P0（全部清零）**
1. 未来日线判定按完整时间戳（同日更晚时间戳行=未来行），防未排序帧隐藏未来行（T2 i8）；
2. amount 缺失/非法时否决回退量能（SPEC §6）（T2 i8）；
3. 双阳量效率分母错误（前量比与效率交叉）（T2 i9）；
4. 空/None 日线绕过新鲜度闸门被当风险计数（T2 i9）；
5. 底部池刷新未绑定显式 asof——未来行可驱动 invalidated/expired（T3 i1）；
6. `--realtime` 解析期跨参数检查导致 `--realtime --select` 顺序错误退出（T3 i1，i2 修为解析后校验）；
7. 状态机延迟刷新竞争：先破位后过期场景被错标 invalidated——改为最早终止事件优先（T3 i2）；
8. fixture 端到端仅有自述无机器证据——`tests/test_bottom_e2e_t3.py` 入库，桥接器在目标 commit 全量执行（T3 i2）。

**P1（全部清零）**：`--realtime` 默认值契约恢复布尔 False 并测试断言；归档碰撞防护
（`reserve_run_dir` 原子占位+序号）贯穿 trends/bottom_scan/信号通道。

## 残余风险（已文档化，非实盘承诺）

- 买点权重仅用于排序不代表概率；总分与收益不单调（SPEC §10、EVALUATION）；
- base_scores 来自单年样本评估，存在过拟合风险，失效时按配置注释回退（config/default.yaml）；
- 大盘 regime 仓位档位是实验结论，未强制写入生产管线（SPEC §11）；
- 回测/研究结果为研究语义，未计交易成本/滑点/涨跌停执行（EVALUATION）。

## NEED_USER

无。各阶段 REVISE 的 P0/P1 均已由执行者修复并通过独立复审；无需要用户裁决的策略变更遗留。

## 提交范围核查（T4 第3项）

- 全链 diff（`748d7c9^..本提交`）仅含：`src/stock_selector/**` 修复、`tests/**` 回归、
  `docs/audit/**` 证据、`SPEC.md` 边界同步；
- `git diff -- data/ .env* *key* *secret* .github/workflows` 为空：未改原始数据、凭据、CI/定时任务；
- `git ls-files` 无凭据类文件；`data/` 仅跟踪 `data/t4/sector_map/csrc_industry_snapshot.json`（历史快照）；
- 远端 tip 与本地 HEAD 一致（审计各轮 remote gate 均验证）。

## 可复现验证方式

1. 全量：`PYTHONPATH=src /root/.hermes/hermes-agent/venv/bin/python3 -m pytest -q`（459/0）；
2. 专项：`pytest tests/test_bottom.py tests/test_bottom_e2e_t3.py tests/test_pipeline_archives_t3.py tests/test_snapshots.py -q`（26/0，含状态竞争三例与离线 e2e 两例）；
3. CLI：9 个子命令 `--help` 全部 exit 0；`bottom-volume --realtime`（无 `--select`）exit 2 并给出用法；
4. T2 语义回归：`tests/test_spec_semantics_t2.py`（72 例）。

## READY_FOR_AUDIT

[DSH-AUDIT]
STATE: READY_FOR_AUDIT
RUN_ID: audit_20260928124829807
HOST_ID: RainYun-c438TDGn
STAGE: T4
ITERATION: 1
HEAD: <本提交哈希>
SUMMARY: T4最终回归：459全过；9个CLI入口help验证+realtime守卫冒烟；全链提交范围核查（无data/凭据/CI改动）；SPEC §9边界同步；最终审计摘要含各阶段commit/修复项/残余风险/复现方式
TESTS: full 459 passed/0 failed/0 errors/0 skipped（/tmp/t4-full.xml）；专项26/0
