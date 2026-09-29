# CSR-8 授权链 v2 任务包设计说明（run 2）

本文件记录 run 2 冻结任务包（`.dsh-audit-task.json`）的设计依据与结构，
供评审与运行所有者核验。任务书原文未修改
（`.feishu-files/20260928140115-CSR8_PHASE_C_PRODUCTION_INFRA_FINAL_TASKBOOK.md`，
SHA256 `9aeb636e2cf9dc8e1b59674e62e9b326e78929384cc5a4e03dd72b4d8a5427c7`）。

## 1. 为什么需要 run 2

父 run `audit_20260928142305936` 的结构性僵局（详见
`docs/audit/CSR8_AUTHZ_CHAIN_STATUS.md` 与 D/iter-1 NEED_USER 裁决）：

1. 任务书 Phase B 的前置是"独立审计**宣告** `C4-D SYNTHETIC FINAL FROZEN`"，
   但桥的阶段机是线性单向的——阶段内任意一轮 APPROVE 即推进；
2. Phase A 获批（iter-16，机器记录 executor-tests-i16.json：目标提交
   `6f9c9af`，隔离 worktree 认证物化零漂移，481/0/exit 0）后，宣告未产生，
   执行者只能提交"合规门槛记录"；门槛记录获批即消耗阶段槽位；
3. B、C 槽位被消耗后，真实工作（B1-B5、C1-C4）在本 run 内已无合法宿主；
   评审员最终以 NEED_USER 拒绝"以批准空操作的方式继续消耗阶段"。

## 2. run 2 的协议修正

| 问题 | run 1 | run 2 |
|---|---|---|
| 授权粒度 | 一个阶段打包多个授权点（B=B1-B7） | **每个授权点独立成阶段**：B1、B2、B3、B4、B5、C1、C2、C3、C4、C5、C6、D、E、F、G（15 阶段；任务书 §6 C4 内嵌的 annotation2/approval2/S2 拆为 C4/C5/C6） |
| Phase A 收官宣告 | 依赖裁决文本中的宣告仪式，永不可达 | **以既定事实为前提**：父 run iter-16 APPROVE + executor-tests-i16.json 机器记录写入 goal，评审可直接核验，不再要求宣告 |
| 空记录推进 | 门槛记录 APPROVE → 阶段被空耗 | 不再存在门槛记录形态；每阶段提交必须是该授权点的真实工作 |
| 裁决历史 | state.lastVerdict 单槽，历史覆盖丢失 | 桥 v0.4.4：每次被接受的裁决全文持久化 `verdicts.jsonl`（commit `07765a7`） |
| 认证输入 | 固定清单，真实域进入后物化必失败 | **每阶段重新生成并提交认证清单**（live 树变化 → 清单同步 → 桥按目标提交零漂移物化复验） |
| 人工授权点 | 无明确交互协议 | B4/C2/C5 明确：执行者先展示 hash+固定措辞（允许一次无 marker 交互轮），人类批准消息落地后才持久化 approval，评审核对流程痕迹 |

## 3. 阶段表（stopAfter = G）

B1 annotator handoff → B2 annotation draft → B3 receipt freeze →
B4 human approval → B5 SEAL+Freeze Gate → C1 proposal → C2 human
NEXT_REVEAL_ONLY → C3 append R2 → C4 annotation2+receipt2 → C5 human
approval2 → C6 S2 SEAL+双周期 Gate → D ordinal-N 泛化 → E runner/watchdog
→ F analysis bridge+audit package → G 最终 FINAL FROZEN gate。

每阶段要求文本内嵌任务书对应 Gate 的机器实测要求（真实函数/真实事务，
禁止静态快照自证、硬编码 PASS、静默跳过——延续父 run 已确立的审计标准）。

## 4. 启动序列（运行所有者操作）

1. `/audit stop`（终止父 run，其目录与 executor-tests-i16.json 永久保留）；
2. `/restart`（桥加载 v0.4.4 裁决持久化代码）；
3. `/audit`（读取 `.dsh-audit-task.json` v2 包创建 run 2，stopAfter=G）。

## 5. 执行者边界（不变）

- 生产链起点 REVEAL=1/SEAL=0，唯一 REVEAL_PACKET 头哈希 `b5ec0ba1…37d5`；
- 不修改 C4-C executor / `c4c_anchor.json` exact bytes（任务书明示新产物除外）；
- 任何冻结/最终宣告只由独立审计作出。
