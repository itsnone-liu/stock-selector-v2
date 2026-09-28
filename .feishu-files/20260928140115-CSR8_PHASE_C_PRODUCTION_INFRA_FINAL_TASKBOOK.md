# CSR-8 / Phase C 基础建设收尾总任务书

## 0. 任务定位

本任务不是继续增加零散补丁，而是完成 CSR-8 / Phase C 从“核心协议与审计底座”到“可持续生产运行基础设施”的最终收口。

当前判断：

- 核心协议、冻结数据、packet、blindness、REVEAL/SEAL、exact-byte binding、authorization、recovery、attempt-history 等底座已经基本完成；
- 剩余工作应以“把现有协议跑成稳定、可重复、可审计的生产闭环”为主；
- 本任务完成并通过独立审计后，宣布：

```text
PRODUCTION INFRA FINAL FROZEN
```

此后基础设施原则上不再进行结构性重构，只允许明确 bug 修复、数据源升级、通过独立设计书扩展的新研究阶段，以及不破坏既有冻结事实的兼容性增强。

---

# 1. 当前冻结基线

## 1.1 Design

```text
C4-D DESIGN v1.0 FINAL FROZEN @ 034d152
```

设计主线：

```text
f9874b5  C4-D DESIGN DRAFT v0.1
d28c02a  DESIGN-FIX1 / v0.2
1af93c5  DESIGN-FIX2 / v0.3
034d152  DESIGN-FIX3 / v0.4 → FINAL FROZEN
```

## 1.2 Synthetic 实现链

```text
dfbf1b1  initial synthetic implementation
dc6e5eb  SYNTH-AUDIT-FIX1
e4819a8  FIX2 (R1–R5)
8479170  FIX3 (R6 + R7 主体)
e022383  FIX4 (R7-A/R7-B)
8074cc7  FIX5 (history barrier at recovery/commit)
8b08f26  FIX6 (sealed-pair replay survives later REVEAL)
```

当前仍不自动宣布 `C4-D SYNTHETIC FINAL FROZEN`；必须先完成本任务 Phase A 的最后收口审计。

## 1.3 不可逆生产事实

当前 production 必须保持：

```text
REVEAL_PACKET = 1
SEAL          = 0
annotation    = 0
outcome       = 0

authorization(first reveal) = CONSUMED
experiment                  = STARTED

G5 = BLOCKED
XP = BLOCKED_FOR_PIT

HARD STOP = active
```

冻结 C4-C public anchor：

```text
production_head_hash
= b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5
```

冻结 FIRST_REVEAL authorization hash：

```text
911d8b844da3a38467aecc0919ee22664484f87c9f49bf445a5a949b6245dc81
```

## 1.4 当前禁止事项

在任何阶段未显式解除 HARD STOP 前，禁止：

```text
创建真实 annotator 域
创建真实 c4d_receipts 域
创建真实 c4d_proposals 域
创建真实 annotation draft
创建真实 receipt
创建真实 seal_approval
production SEAL
ordinal-2 production proposal
ordinal-2 production approval/permit
第二条 production REVEAL
outcome 读取/解盲
G5 纳入主统计
XP 进入 PIT 统计
修改 C4-C executor
修改 c4c_anchor.json
```

---

# 2. 最终目标

本任务要把系统推进到：

```text
Frozen data / C3 packet pool
        ↓
Blinded progressive annotation
        ↓
Exact receipt freeze
        ↓
Human exact-hash approval
        ↓
SEAL transaction
        ↓
Recovery / replay / audit
        ↓
Next ordinal authorization
        ↓
R2 / S2 second-cycle validation
        ↓
General ordinal-N production runner
        ↓
Analysis-ready annotation corpus
        ↓
PRODUCTION INFRA FINAL FROZEN
```

最终完成标准不是“单个 synthetic fixture 全绿”，而是同时满足：

```text
1. protocol frozen
2. synthetic frozen
3. first real cycle complete
4. second real cycle complete
5. ordinal-N loop generalized
6. crash/recovery verified
7. authorization flow generalized
8. production runner frozen
9. audit/export bridge frozen
10. analysis-ready corpus contract frozen
```

---

# 3. 总体阶段

```text
A. C4-D synthetic 最终收口
B. Real Cycle-1：R1 → Annotation1 → S1
C. Real Cycle-2：R2 → Annotation2 → S2
D. ordinal-N progressive loop 泛化
E. Production runner + recovery/watchdog
F. Analysis-ready bridge + audit package
G. PRODUCTION INFRA FINAL FREEZE
```

每个阶段均有：

```text
ENTRY GATE
IMPLEMENTATION
NEGATIVE FIXTURES
AUDIT
HARD STOP
FREEZE
```

任何阶段不得自动越级。

---

# 4. Phase A — C4-D Synthetic 最终收口

## 4.1 目标

关闭当前 synthetic executor 的最后授权边界，保证：

```text
[R1,S1]       → ordinal-2 proposal allowed
[R1,S1,R2]    → ordinal-3 proposal forbidden
[R1,S1,R2,S2] → ordinal-3 proposal 才有资格 allowed
```

不得依赖模糊 lifecycle 名称判断，而应直接从 trusted production chain 派生“当前 open reveal 是否为 0”。

## 4.2 必须实现

新增统一 helper，例如：

```python
prove_next_reveal_eligible(sb, sid, ordinal)
```

必须至少证明：

```text
C2 full verify(check_head=True) PASS
requested ordinal == reveal_count + 1
last committed event == SEAL_ANNOTATION
open_reveals == 0
revealed set == candidate total-order prefix
previous reveal 已有合法 matched SEAL
previous sealed pair semantic replay PASS
```

该 proof 至少接入：

```text
build_next_reveal_proposal
approve_next_reveal
materialize_next_permit
verify_next_authorization_chain
reveal_transaction
```

最关键的是 proposal 创建前和真正 append REVEAL 前都要重新证明。

## 4.3 Fixture

新增：

```text
D71  [R1,S1,R2] 下 ordinal-3 proposal
     → G-C4D-AUTHZ
     → proposal ABSENT
     → approval ABSENT
     → permit ABSENT
```

正向控制：

```text
[R1,S1]
→ ordinal-2 proposal PASS
```

若不实现 R2/S2 synthetic，则不要求 `[R1,S1,R2,S2] → ordinal-3` 正向。

## 4.4 Synthetic Final Gate

必须通过：

```text
D01–D71 ALL PASS
C4-C regression PASS
candidate gates PASS
blindness output scan CLEAN
real fingerprint before == after
real production remains REVEAL=1 / SEAL=0
forbidden real domains absent
c4c_anchor exact bytes unchanged
```

通过独立审计后才允许宣布：

```text
C4-D SYNTHETIC FINAL FROZEN @ <sha>
```

## 4.5 HARD STOP A

冻结后暂停。不得自动进入真实 annotation。

---

# 5. Phase B — Real Cycle-1：R1 → Annotation1 → S1

此阶段是第一个真实生产闭环，必须拆成多个独立授权点。

## B1. Real annotator handoff

仅允许：

```text
创建真实 annotator domain
exact-copy handoff 当前 R1 packet
创建 annotation session registry
```

禁止 receipt / approval / SEAL / R2 proposal / outcome。

Gate：

```text
packet exact bytes == C2 archived R1 bytes
packet_sha256 == R1 payload
annotator domain closed-world
no identity leak
no future leak
no outcome leak
annotation_session_id opaque
```

完成后 HARD STOP。

## B2. Real annotation draft

生成真实 blinded annotation。

annotation contract：

```text
rt_H01..rt_H06
observability ∈ {OBSERVABLE, UNOBSERVABLE}

support ∈ {
  SUPPORTED_STRONG,
  SUPPORTED_PARTIAL,
  MIXED,
  NOT_OBSERVED,
  CONTRADICTED
}
```

规则：

```text
OBSERVABLE   → support 必填且属于闭集
UNOBSERVABLE → support = null
```

flags：

```text
DATA_QUALITY_ISSUE
EVIDENCE_INCOMPLETE_AT_T
PACKET_PARSE_ANOMALY
FLAGGED_FOR_REVIEW
```

`evidence_refs` 必须是合法 JSON Pointer 且 resolve 到当前 packet。

Gate：

```text
draft closed-world
annotation_contract_sha256 exact
no missing/duplicate hypotheses
canonical contract preimage re-check
annotation_session_id per-attempt unique
timestamps valid
no outcome access
```

完成后 HARD STOP。

## B3. Real receipt freeze

事务顺序：

```text
read exact D
→ full validation
→ staging receipt + exact snapshot(D)
→ fsync files + staging dir
→ chmod active draft 0400
→ reread == D
→ fsync draft + parent
→ RENAME_NOREPLACE
→ fsync ordinal parent
```

必须成立：

```text
attempt exists
⇒ receipt + snapshot complete
⇒ draft locked 0400
⇒ active draft bytes == snapshot
```

receipt：

```text
draft_sha256 = SHA256(exact draft_snapshot.bin)
```

完成后 HARD STOP。

## B4. Human exact-hash approval

只展示：

```text
receipt_sha256
```

人工批准措辞固定，例如：

```text
我明确批准 SEAL_ANNOTATION_ONLY receipt exact hash:
<64 hex>

该批准仅授权当前 session / reveal / attempt 所绑定的
这一份 exact receipt bytes，不授权任何其他 receipt、REVEAL、
outcome 或 next ordinal。
```

随后才允许持久化 `seal_approval.json`，必须 O_EXCL / canonical / 0600 / fsync。

完成后 HARD STOP。

## B5. Real SEAL transaction

提交前必须重新证明：

```text
trusted C2 prefix valid
whole attempt history valid
active attempt unique
receipt/snapshot exact
approval exact
active packet exact
active draft 0400 + exact
commit-time history proof PASS
commit-time receipt proof PASS
persisted receipt reread == proven rbytes
```

然后唯一允许：

```text
SEAL_ANNOTATION append once
```

append：

```text
payload.receipt_sha256 = SHA256(exact proven rbytes)
C2 content_bytes = same rbytes
```

事务后：

```text
C2 full verify PASS
semantic replay PASS
SEAL_COMMITTED
```

之后：

```text
c4d_seal_anchor durable
workspace cleanup
POST_SEAL_FINAL
```

得到 S1 SEALED。

### B5 Freeze Gate

```text
chain == [R1,S1]
head == S1
receipt triple exact-byte equality PASS
approval consumed
attempt history PASS
active workspace empty
c4c_anchor unchanged
c4d_seal_anchor exact
outcome untouched
```

完成后 HARD STOP。

---

# 6. Phase C — Real Cycle-2：R2 → Annotation2 → S2

这是判断“基础设施是否真正可循环”的关键阶段。

## C1. ordinal-2 proposal

前置必须直接从 committed chain 派生：

```text
[R1,S1]
open_reveals == 0
S1 replay PASS
candidate prefix == 1
```

生成 selector-only：

```text
ordinal-0002/next_reveal.proposal.json
```

human 只看到 `proposal_sha256`。

完成后 HARD STOP。

## C2. Human NEXT_REVEAL_ONLY approval

批准 exact proposal hash。

持久化：

```text
next_reveal.approval.json
next_reveal.permit.json
```

三方一致：

```text
proposal exact bytes
== approved hash
== permit exact bytes
```

完成后 HARD STOP。

## C3. Append R2

必须得到：

```text
[R1,S1,R2]
```

并证明：

```text
C2 full verify PASS
authorization(2) == CONSUMED
S1↔R1 replay remains PASS
candidate prefix == 2
```

完成后 HARD STOP。

## C4. Annotation2 / Receipt2 / Approval2 / S2

完整重复 B2–B5，但所有 artifact 必须进入：

```text
ordinal-0002/
```

最终：

```text
[R1,S1,R2,S2]
```

### 双周期最终 Gate

```text
R1↔S1 exact pairing PASS
R2↔S2 exact pairing PASS
ordinal-1 attempt history PASS
ordinal-2 attempt history PASS
authorization(1) consumed
authorization(2) consumed
open_reveals == 0
candidate revealed prefix == 2
两个 sealed pair 后续 replay 互不污染
crash/recovery semantics 在 ordinal-2 仍成立
```

若此 Gate 不通过，不得宣称 production loop 已稳定。

---

# 7. Phase D — ordinal-N Progressive Loop 泛化

双周期通过后，把特殊的 ordinal-1/2 逻辑抽象成统一 production engine。

目标 API 示例：

```python
current_progress()
prove_ordinal_state(n)
candidate_for_ordinal(n)
prove_next_reveal_eligible(n)
create_next_reveal_proposal(n)
approve_next_reveal(n)
append_reveal(n)
open_annotation(n)
freeze_receipt(n)
approve_seal(n)
append_seal(n)
finalize_seal(n)
recover_ordinal(n)
```

禁止大量：

```text
if ordinal == 1: ...
elif ordinal == 2: ...
```

除不可变 legacy compatibility：ordinal-1 C4-C historical payload。

## D1. General invariant

任意 k：

```text
completed prefix:
R1,S1,R2,S2,...,Rk,Sk

open state:
R1,S1,...,Rk,Sk,R{k+1}
```

只允许：

```text
sealed prefix + at most one open reveal
open_reveals ∈ {0,1}
```

永远禁止连续两个未封存 reveal。

## D2. General recovery

任意 ordinal 都必须支持：

```text
partial log tail
matched orphan
foreign orphan
unanchored SEAL tail
head stale
anchor missing
workspace cleanup pending
attempt publication crash
approval/permit crash
```

且不得污染其它 ordinal。

## D3. General history proof

每个 ordinal：

```text
attempt history independently scoped
sealed pair independently replayable
later ordinal 不改变 earlier ordinal proof
```

---

# 8. Phase E — Production Runner / Watchdog / Recovery

## 8.1 Runner

实现显式状态机 runner：

```text
inspect
proposal
handoff
draft
freeze
await_approval
seal
finalize
recover
status
```

任何 command 默认 read-only or single-purpose。

禁止“一条命令自动跑完全流程”。

## 8.2 Resume

runner 必须从 persisted facts 恢复，而不是依赖内存状态。

重启后必须能派生：

```text
current committed prefix
open ordinal
authorization state
annotation state
seal state
finalize state
```

## 8.3 Watchdog

只允许观察：

```text
filesystem invariants
head/log parity
pending staging
partial tail
anchor parity
permission drift
unexpected forbidden domains
```

watchdog 默认 `REPORT ONLY`，不得自动 SEAL、REVEAL、approve 或删除 forensic evidence。

## 8.4 Recovery command

所有恢复必须显式：

```text
recover --dry-run
recover --apply
```

`--dry-run` 输出：

```text
derived state
planned mutation
affected exact paths
expected before/after hashes
```

任何 FORENSIC：HALT，不得自动修复。

---

# 9. Phase F — Analysis-ready Bridge

## 9.1 Immutable Annotation Corpus

输出规范化表，例如：

```text
phase_c_annotation_corpus.parquet
```

一行最小 grain：

```text
session_id
reveal_ordinal
opaque_case_id
T
packet_id
packet_sha256
reveal_event_hash
seal_event_hash
receipt_sha256
annotation_attempt
annotation_session_id
hypothesis_id
observability
support
evidence_refs
evidence_note
flags
receipt_created_at
sealed_at
```

要求：

```text
只从 persisted frozen artifacts + C2 chain 导出
不从 active workspace 导出
不现场重建 annotation
```

## 9.2 Blinding Boundary

annotation 阶段：

```text
outcome unavailable
identity unavailable
future unavailable
```

研究解盲阶段才允许单独 join：

```text
annotation corpus
× hidden case identity
× forward outcomes
```

必须是一个新的显式阶段，不得由 annotation runner 隐式执行。

## 9.3 Outcome Join Contract

必须明确：

```text
join key
PIT boundary
forward horizon clock
missingness
censoring
group eligibility
G5 handling
XP handling
```

G5 继续 `PROVISIONAL_BLOCKED`。

XP 继续 `BLOCKED_FOR_PIT`，除非另有独立正式解封设计。

## 9.4 Audit package

至少输出：

```text
infra_manifest.json
production_chain_snapshot.json
sealed_pair_manifest.parquet
annotation_corpus_manifest.json
authorization_manifest.json
recovery_audit.json
gate_results.json
public_anchor_manifest.json
```

每个文件含：

```text
schema_version
source commit
source hashes
row counts
sha256
created_at
```

---

# 10. Phase G — Production Infra Final Freeze

只有以下全部满足，才允许宣布 `PRODUCTION INFRA FINAL FROZEN`。

## G1. Frozen design

```text
C4-D design frozen
ordinal-N production contract frozen
analysis-ready bridge frozen
```

## G2. Synthetic

```text
all synthetic fixtures PASS
legacy C4-C regression PASS
real fingerprint before == after
```

## G3. Real double-cycle

```text
R1,S1,R2,S2 persisted
full C2 verify PASS
two sealed pairs replay independently PASS
```

## G4. Authorization

```text
FIRST_REVEAL auth immutable
ordinal-2 auth consumed
authorization chain independently replayable
no reused authorization
```

## G5. Exact bytes

每个 sealed pair：

```text
persisted receipt SHA
== SEAL payload
== C2 archived bytes SHA
```

## G6. Recovery

至少实证：

```text
receipt publish crash
SEAL append crash
unanchored tail
anchor missing
cleanup pending
permission drift
foreign orphan
restart/resume
```

全部 fail-closed。

## G7. Blindness

机器证明：

```text
annotator surface no identity
no future
no outcome
human authorization UI no packet identity
```

## G8. Candidate order

```text
revealed set == total-order prefix
no duplicate packet
no ordinal skip
deterministic recompute
```

## G9. Audit corpus

```text
sealed_pair_manifest reproducible
annotation corpus reproducible
all source hashes committed
```

## G10. Production cleanliness

```text
no staging leftovers
no stale active workspace
no unresolved FORENSIC
no partial tail
head/log exact
anchors exact
git worktree clean
```

---

# 11. 最终状态机

完整生产系统最终应支持：

```text
SEALED PREFIX
    ↓
NEXT_REVEAL proposal
    ↓
human exact-hash approval
    ↓
REVEAL
    ↓
ANNOTATION_OPEN
    ↓
READY_TO_SEAL
    ↓
human exact-hash SEAL approval
    ↓
SEAL_AUTHORIZED
    ↓
SEAL_COMMITTED
    ↓
FINALIZE
    ↓
SEALED PREFIX + 1
```

并保持：

```text
任意时刻最多 1 个 open reveal
任意 ordinal 最多 1 个 committed SEAL
任意 authorization 只能消费一次
任意 receipt 只能被一个 SEAL 消费
历史 attempt 永久保留
revoked attempt 永久 ineligible
```

---

# 12. 不得做的事情

```text
为赶进度降低 exact-byte 校验
把 head 当 cache
绕过 trusted-head replay
把 malformed state 自动修成“看起来正常”
删除 forensic evidence
用 outcome 辅助 annotation
用身份信息辅助 annotation
提前创建下一 ordinal authorization
跳过人工 exact-hash approval
把 synthetic approval 当真实 production approval
自动批量 REVEAL
自动批量 SEAL
自动解盲
```

---

# 13. Commit / Freeze 纪律

每个阶段必须独立提交。

建议命名：

```text
C4-D-SYNTH-FINAL
C4-D-REAL-CYCLE1-HANDOFF
C4-D-REAL-CYCLE1-ANNOTATION
C4-D-REAL-CYCLE1-RECEIPT
C4-D-REAL-CYCLE1-SEAL
C4-D-REAL-CYCLE2
PHASE-C-ORDINAL-N
PHASE-C-PRODUCTION-RUNNER
PHASE-C-ANALYSIS-BRIDGE
PRODUCTION-INFRA-FINAL
```

每次提交前：

```text
tests PASS
negative fixtures PASS
worktree scope checked
real fingerprint checked
forbidden domains checked
anchors checked
```

任何 production irreversible action 后：

```text
立即 commit runtime/public proof artifact
立即独立审计
HARD STOP
```

---

# 14. 最终交付物

基础建设全部完成时，至少应交付：

```text
1. frozen design docs
2. frozen synthetic executor
3. ordinal-N production engine
4. production runner
5. recovery/watchdog
6. double-cycle production proof
7. authorization manifests
8. sealed-pair manifests
9. annotation corpus exporter
10. analysis-ready bridge
11. audit package
12. final gate report
13. PRODUCTION_INFRA_FINAL_FROZEN marker
```

最终 marker 应记录：

```text
design_commit
synthetic_commit
production_engine_commit
cycle1_head
cycle2_head
candidate_order_commitment
annotation_contract_sha256
C3_manifest_commitment
first_reveal_authorization_sha256
public anchors
gate result summary
audit package hashes
```

---

# 15. 最终宣告条件

只有独立审计确认全部 Gate 通过后，才允许宣布：

```text
CSR-8 / Phase C
PRODUCTION INFRA FINAL FROZEN
```

其含义是：

> 数据、packet、blindness、annotation、receipt、authorization、REVEAL、SEAL、recovery、ordinal-N 调度、审计和 analysis-ready bridge 已形成可持续、可复现、可独立审计的生产闭环。

此后项目正式从：

```text
基础建设阶段
```

进入：

```text
持续 blinded annotation
+
资金行为 / 路径 / hypothesis 实证研究阶段
```

---

# 16. 执行入口

执行 agent 从以下顺序开始：

```text
Step A1
先审当前 HEAD 与 8b08f26 之后的实际状态

Step A2
完成 next-reveal prerequisite guard + D71

Step A3
跑 full synthetic + C4-C regression + real fingerprint

Step A4
提交并暂停

Step A5
等待独立审计宣布：
C4-D SYNTHETIC FINAL FROZEN

然后才允许进入 Phase B。
```

**严禁跳过 HARD STOP。**
