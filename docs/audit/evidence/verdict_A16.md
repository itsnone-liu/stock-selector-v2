# Phase A iter-16 独立裁决原文存档（更正版）

> **勘误与来源说明**：本文件此前的版本是错误存档——生成时审计桥的
> `state.json: lastVerdict` 已被 Stage B iter-1 裁决覆盖，导致误存 B/iter-1
> 内容（元数据 `stage: B / iteration: 1`）。C/iter-1 裁决指出了该错误。
> 本版为**真正的 Phase A iter-16 裁决**逐字内容，来源：执行者会话在
> Stage B 阶段提示送达后、B/iter-1 裁决产生前对 `state.json:lastVerdict`
> 的读取输出（彼时该字段即 A-16 裁决，commit `6f9c9af`）。桥运行存储仅
> 保留最近一次裁决、无历史裁决文件，建议审计基础设施补全裁决历史持久化。

- verdict: **APPROVE** | stage: A | iteration: 16
- commit: 6f9c9af8c4fca7f36bd0bee0d349546f0304621f

## summary

- 目标提交满足 Phase A / C4-D synthetic closeout 的冻结要求，统一 next-reveal prerequisite guard 已获得静态接入与运行时行为验证。
- D01-D71 全量 synthetic、D71 负向场景、ordinal-2 正向控制、C4-C regression、candidate gates、blindness、真实状态及 fingerprint 不变性均由桥接器在精确目标提交上执行通过。
- 未发现 C4-C executor 或 c4c_anchor.json 被修改，也未发现进入 Phase B 或创建被禁止真实 C4-D 域的证据。

## evidence

- 远端 main tip 已验证为目标提交 6f9c9af8c4fca7f36bd0bee0d349546f0304621f；审计范围为 44c54c261875a82e756b8449ed57b8c31270860a..6f9c9af8c4fca7f36bd0bee0d349546f0304621f。
- CHANGED_FILES 仅列出 Phase-A 审计配置、文档、公开状态、审计脚本、C4-D synthetic executor 和测试；不包含 scripts/csr8_phase_c_first_reveal.py 或 c4c_anchor.json。
- tests/test_csr8_phase_a.py 的 AST 检查确认 prove_next_reveal_eligible 调用 C2 `verify(check_head=True)`，检查 ordinal 等于 reveal_count+1 和末事件为 SEAL，并接入 proposal、approval、permit、authorization-chain verify 与 reveal_transaction 五个入口。
- 同一测试文件运行真实 C4-D 函数验证 `[R1,S1]` 可创建 ordinal-2 授权链；在 `[R1,S1,R2]` 下 ordinal-3 的 proposal、approval、permit 均以 G-C4D-AUTHZ 拒绝，且 proposal 与 authorization artifact 域保持不存在。
- 多 sealed-pair 测试实际构造 `[R1,S1,R2,S2]`，随后 prove_next_reveal_eligible 对 ordinal-3 成功，覆盖合法前次 matched SEAL、sealed-pair replay 与后续 ordinal 连续性。
- scripts/csr8_phase_a_machine_audit.py 执行完整 D01-D71 registry，要求顺序精确为 D01 至 D71，并强制执行 C4-C regression、live_preflight、candidate gates、公开输出 blindness scan 和 real fingerprint equality。
- 审计桥在精确 TARGET_COMMIT 的隔离 detached worktree 上执行 pytest：481 passed、0 failed、0 errors、0 skipped，退出码为 0。
- 桥接器从目标提交读取并验证 config/audit/certified_live_inputs.json，成功认证并物化 2 个完整根、10526 个文件、813372397 字节，mismatches 为空；提交内测试随后再次逐文件验证 hash、大小、mode、缺失项和额外项。
- 通过的机器审计断言包括 certified_inputs=VERIFIED、D01_D71=PASS、C4D=PASS、C4C_regression=PASS、candidate_gates=PASS、blindness=PASS、real_fingerprint=UNCHANGED、production_snapshot=`REVEAL=1 SEAL=0`。
- 公开状态文件记录生产链仅含一个 REVEAL_PACKET、reveal_count=1、seal_count=0、production_head_hash=b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5；测试同时核对认证后的真实 sealing log 首事件 hash。
- 测试逐字节核对 c4c_anchor.json 为冻结内容，并检查真实 annotator、c4d_receipts、c4d_proposals 域均不存在；公开 JSON 扫描未出现 opaque_case_id、packet_id、case_key、secret_salt 或 outcome。
- docs/audit/CSR8_PHASE_A_FINAL.md 明确限定为 Phase A evidence index，声明独立审计前不进入 Phase B，也不把本提交表述为整体生产基础设施最终冻结。

## p0 / p1

- p0: []
- p1: []

## residualRisks

- 主实现与认证 manifest 在展示包中因体积被截断，但桥接器已在完整 git 对象对应的精确目标提交上执行全部测试，并对认证输入进行零漂移校验；本批准依赖该机器验证记录。
- certified live inputs 证明的是桥接测试时的真实输入快照；未来任何文件、mode、目录或额外条目漂移都必须重新认证并重新运行审计。
- 本批准仅覆盖 STAGE A；不授权进入 Phase B、执行真实 SEAL、ordinal-2 production approval/permit、第二次 production REVEAL、outcome 读取或宣布 PRODUCTION INFRA FINAL FROZEN。
