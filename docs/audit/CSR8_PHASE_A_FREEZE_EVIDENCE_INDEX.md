# CSR-8 Phase A 冻结证据索引 —— C/iter-1 证据包（无 Real Cycle-2 执行）

本提交是 Stage C 第 1 轮迭代的产物。**未执行任何 Phase C Real Cycle-2 工作、
未执行任何 B1-B7 授权点、未创建真实 C4-D 域、未 production SEAL、未第二次
production REVEAL、未读取 outcome。** 生产链保持 `REVEAL=1 / SEAL=0`。

## 目的

Phase B iter-1 裁决（APPROVE，门槛记录合规）的残余条款指出：本轮证据包
"未提供完整目标树清单或此前裁决原文"、"当前机器证据未包含足以重新审计
Phase A 全部冻结要求的材料；因此本裁决不补作或推定 Phase A 收官宣告"。
本证据包逐项补齐该材料，供独立审计作出（或继续拒绝作出）任务书要求的
`C4-D SYNTHETIC FINAL FROZEN` 宣告。

## 证据文件

| 文件 | 内容 |
|---|---|
| `docs/audit/evidence/verdict_A16.md` | Phase A iter-16 独立裁决原文机器存档（summary / evidence / p0 / p1 / residualRisks 逐字） |
| `docs/audit/evidence/target_tree_6f9c9af.txt` | Phase A 获批目标提交 `6f9c9af` 的完整 git 跟踪树清单（838 文件，`git ls-tree -r --name-only`） |

## Phase A 冻结要求 → 机器证据映射

Phase A 阶段要求原文（run manifest stageRequirements.A）逐句映射：

| # | 冻结要求（A1-A4 范围内） | 机器证据（本 HEAD 提交内测试，桥在隔离 worktree 独立复跑） |
|---|---|---|
| 1 | 统一 next-reveal prerequisite guard：C2 `verify(check_head=True)`、ordinal==reveal_count+1、last event=SEAL、open_reveals=0、revealed set 为 candidate total-order prefix、前次合法 matched SEAL、sealed pair semantic replay PASS | `tests/test_csr8_phase_a.py` AST 断言 `prove_next_reveal_eligible` 调用 C2 `verify(check_head=True)` 并检查 ordinal 与末事件 SEAL；运行时用真实 C4-D 函数构造 `[R1,S1]`/`[R1,S1,R2,S2]` 验证 ordinal-2/3 行为 |
| 2 | guard 接入 proposal 创建前、approval、permit、authorization-chain verify、append REVEAL 五入口 | 同上 AST 检查列出全部五个接入点 |
| 3 | D71 负向：`[R1,S1,R2]` 下 ordinal-3 proposal 得 `G-C4D-AUTHZ` 且 proposal/approval/permit absent | `test_csr8_phase_a.py` D71 用例；machine-audit JSON `D01_D71=PASS` |
| 4 | D01-D71 全量 synthetic + C4-C regression + candidate gates + blindness scan + real fingerprint before==after | `scripts/csr8_phase_a_machine_audit.py` 顺序强制 D01→D71 并输出 `C4C_regression/candidate_gates/blindness/real_fingerprint` 键；wrapper 测试断言全部 PASS/UNCHANGED |
| 5 | 真实生产 REVEAL=1/SEAL=0、禁止域不存在、c4c_anchor.json exact bytes 未变 | 同测试逐字节核对 anchor、检查 `annotator/`、`c4d_receipts/`、`c4d_proposals/` 不存在、`production_snapshot=REVEAL=1 SEAL=0`、唯一 REVEAL_PACKET 头哈希 `b5ec0ba1…37d5` |
| 6 | 认证输入（i16 新增，消除"提交内测试必然失败"） | 提交内 `config/audit/certified_live_inputs.json`（v2，2 根 / 10526 文件 / 813372397 字节）；桥从目标提交读清单、零漂移物化后，提交内测试再逐文件校验 hash/size/mode/缺失/多余 |

桥侧独立执行记录（iter-16 评审时生成）：目标提交 `6f9c9af` 上
**481 passed / 0 failed / 0 errors / 0 skipped，exit 0**；certifiedInputs
物化 2 roots / 10526 files / 813372397 bytes / mismatches=[]。
本 HEAD（含本证据包）上同一测试套将由桥再次独立复跑。

## 请求

1. 若本证据包 + 桥侧复跑记录满足"重新审计 Phase A 全部冻结要求"：
   请在裁决中显式宣告 `C4-D SYNTHETIC FINAL FROZEN`。宣告后 B1 作为第一个
   独立授权点执行并 HARD STOP。
2. 若仍有缺口：请 REVISE 列出具体缺口条目，执行者按条补证。

执行者不自行宣布任何冻结。
