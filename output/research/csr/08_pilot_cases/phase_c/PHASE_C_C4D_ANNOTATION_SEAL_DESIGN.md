# CSR-8 Phase C4-D — First Annotation + SEAL Protocol Design

- 状态：DESIGN DRAFT v0.4（= v0.3 @ `1af93c5` + C4-D-DESIGN-FIX3 修订，
  三处最终一致性收口 F17/F18/F19 已全部落入正文）；待用户审计；本文件
  不授权、不实现、不创建任何 production 对象、不创建 annotator 域与
  c4d_receipts 域、不产生任何 production event
- 基线（全部已冻结）：
  - C2 seal log FINAL FROZEN @ `9d19be7`（`REVEAL_PACKET` / `SEAL_ANNOTATION`
    事件语义、exact-byte binding、strict REVEAL→SEAL 交替、**head anchor
    MANDATORY——trusted committed prefix 语义，本设计不得重定义**）
  - C1 packet FINAL FROZEN @ `9292d0d`；C3 preflight FINAL FROZEN @
    `04f54e1`（commitment
    `883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b`）
  - C4 DESIGN v1.0 FINAL FROZEN @ `6fa5380`；C4-A/B FINAL FROZEN @ `4482e54`
  - C4-C 设计 FINAL FROZEN @ `4d9d29c`；SYNTHETIC FINAL FROZEN @ `aa04403`；
    FIRST REVEAL COMMITTED @ `54efaf5`；EXEC-RECOVERY FINAL FROZEN @
    `1d9ba55`；C4-C public anchor（`c4c_anchor.json`）= 历史冻结事实，
    **字节永不改动**（F9）
  - CSR-7 case protocol（annotation blindness contract、progressive
    sealing、rt_blind_packet、hypothesis_block——本设计逐项复制冻结，
    不重定义标注学语义）
- 设计阶段必须保持的状态：

```text
PRODUCTION_EVENT_COUNT = 1   （exactly one REVEAL_PACKET）
production_head_hash   = b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5
authorization          = 911d8b84…5dc81 = CONSUMED（不再承担任何后续意义）
SEAL                   = 0
annotation             = 0   （annotator 域与 c4d_receipts 域均尚不存在）
outcome                = 0
G5                     = BLOCKED
XP                     = BLOCKED_FOR_PIT
experiment             = STARTED
HARD_STOP              = active（等待 C4-D 设计冻结 + 逐步人工授权）
```

## 0. FIX1 修订记录（v0.1 → v0.2）

| 项 | 修订 | 落点 |
| --- | --- | --- |
| F1 | receipt/frozen-draft 独立 selector-only `c4d_receipts` 域（含 `draft_snapshot.bin`） | §2.1 §4.2 §4.6 |
| F2 | 取消"head 是 cache"表述；`SEAL_TAIL_UNANCHORED` 严格完成条件；trusted head = committed prefix | §5.3 |
| F3 | partial JSONL tail 截断恢复 | §5.3 |
| F4 | persisted SEAL exact-hash approval authority + `SEAL_AUTHORIZED` 态 | §3 §4.4 |
| F5 | annotation_attempt + append-only revocation tombstone；receipt 永不删除 | §3 §4.5 |
| F6 | SEAL 后清空 active annotator workspace | §3 §6.4 |
| F7 | `candidate_for_ordinal(n)` 全序（round-robin，ordinal-1 与 C4-C 一致） | §7.3 |
| F8 | 完整 CSR-7 hypothesis/flags 闭集逐项冻结 + `annotation_contract_sha256` | §4.1 |
| F9 | 独立 `c4d_seal_anchor.json`；C4-C anchor 字节不动 | §8 |
| F10 | `evidence_refs`（JSON Pointer 结构校验）与 `evidence_note`（自由文本）分离 | §4.1 |
| 裁决1 | `annotator_id` → `annotation_session_id`（session identity，非 person identity） | §4.1 |
| 裁决2 | hypothesis 完整冻结集不裁剪（含 v0.1 verdict 枚举错误的更正） | §4.1 |
| 裁决3 | receipt 作废 = append-only tombstone，永不删除 | §4.5 |
| 裁决4 | SEAL 后清除 active annotator workspace | §6.4 |
| 裁决5 | ordinal-2 人工授权只看 `proposal_sha256`，措辞固定 | §7.4 |

## 0.2 FIX2 修订记录（v0.2 → v0.3）

| 项 | 修订 | 落点 |
| --- | --- | --- |
| C1 | contract exact hash preimage 逐字节写进文档（canonical 单行 JSON + 序列化规则），可独立复算 | §4.1.1 |
| C2 | 孤儿 SEAL bytes 区分 `MATCHED_ORPHAN`（可 retry）/`FOREIGN_ORPHAN`（FORENSIC，禁止覆盖）；partial-tail 截断后同判据 | §5.3 |
| C3 | receipt+draft_snapshot 同目录 staging 完整构造 → fsync → RENAME_NOREPLACE 原子发布整个 attempt；消除半状态窗口 | §4.3 §4.6 |
| C4 | SEAL 后拆分 `SEAL_COMMITTED → anchor durable → cleanup → POST_SEAL_FINAL/SEALED`；新增 `SEALED_PENDING_FINALIZE` 恢复（只补 anchor/cleanup，绝不再次 append）；修正 v0.2 §5.2/§6.3 顺序矛盾 | §3 §5.2 §6.3 §6.4 |
| C5 | ordinal-N 完整 persisted protocol：proposal/approval/permit 固定路径 + 0700/0600/O_EXCL/fsync 契约 + REVEAL payload 扩展字段（链导出消费证明） | §7.2 §7.5 |
| fixtures | D40–D45 | §9 |

## 0.3 FIX3 修订记录（v0.3 → v0.4；最终一致性收口）

| 项 | 修订 | 落点 |
| --- | --- | --- |
| F17 | `c4d_proposals` selector-only 0700/0600 契约（proposal 由 0644 改 0600，全路径父目录 0700，列入 §2.1 selector-only 域；0644 无法机器证明 proposal 对 annotator 不可见）；human UI 仍只输出 proposal_sha256；fixture D46 | §2.1 §7.2 §9 |
| F18 | §5.3 `SEAL_TAIL_UNANCHORED` 完成提交的终态由 SEALED 更正为 **SEAL_COMMITTED**（sync_head+fsync+verify+semantic replay 之后），再走 anchor durable → cleanup → POST_SEAL_FINAL → SEALED；与 FIX2-C4 分相全文一致 | §5.3 |
| F19 | draft 锁定并入 attempt 发布事务（8 步冻结顺序：锁 0400 + reread exact + fsync **先于** renameat2）；invariant：attempt 存在 ⇒ draft 已锁且 bytes==snapshot；crash 在锁后/rename 前的恢复 = 清 staging + 确认无 committed attempt + chmod 回 0600 → ANNOTATION_OPEN；attempt 已存在时 draft 漂移 = FORENSIC 不静默修正（D22 确定语义）；D41 扩展两窗口 | §4.3 §3 §9 |

---

## 1. 设计范围与不动点

C4-D 回答四个问题：

1. 第一 packet 已经 REVEAL 后，annotator 究竟取得什么（可见性边界）；
2. annotation 从草稿到 SEALED 的生命周期与字节身份；
3. SEAL 事务如何把 exact annotation bytes 绑进 C2 hash chain（含 crash
   recovery）；
4. 第二 packet 在什么条件下才重新获得 reveal 权限（ordinal 授权链）。

**不动点（本设计与后续一切 C4-D 实现不得触碰）：**

- 冻结 C2 `csr8_phase_c_seal.py` 一字不改；**C2 的 trust model 不被重
  定义：head anchor 是 mandatory 的 committed-prefix 证明**，本设计只
  以调用者身份使用 `append / verify(check_head) / read_events /
  sync_head` API；
- 已冻结的 C4-C executor 语义不改；`c4_public/c4c_anchor.json` 原字节
  永不改动（F9）；
- live production chain 恰一条 REVEAL_PACKET（event_hash
  `b5ec0ba1…437d5`）；任何 C4-D synthetic 测试只碰 sandbox；
- `911d8b84…5dc81` 已消费；C4-D 一切新授权使用新 schema、新 scope、
  新 hash（§7）。

---

## 2. 可见性三分域（annotator visibility / reveal boundary）

### 2.1 四个域定义

```text
selector-only     data/csr8_phase_c/secret/            （salt、packet_plan、
                                                       真实 code↔ocid 映射）
                  data/csr8_phase_c/production/        （sealing chain、
                                                       authorization）
                  data/csr8_phase_c/c3_preflight/      （全部 packet 池）
                  data/csr8_phase_c/c4c_proposals/     （C4-C 历史 proposal 域）
                  data/csr8_phase_c/c4d_proposals/      （FIX3-F17：ordinal-N
                                                       reveal proposal 域，
                                                       0700/0600，含下一
                                                       packet identity，
                                                       selector-only）
                  data/csr8_phase_c/c4d_receipts/      （F1：annotation 控制
                                                       域，见 §4.6）

annotator-visible data/csr8_phase_c/annotator/c4-prod-0002/
                  ├── packet/<packet_id>.json          （exact bytes copy，
                  │                                    任一时刻 ≤1 个文件）
                  └── draft/annotation_draft.json      （active 工作区，
                                                       ≤1 个文件）

public            output/research/csr/08_pilot_cases/phase_c/c4_public/
                  ├── c4c_anchor.json                 （C4-C 冻结事实，只读）
                  └── c4d_seal_anchor.json            （F9：C4-D 新增）
```

annotator-visible 域与 `c4d_receipts` 域均 0700/0600、gitignore。
annotator active workspace 的文件集合是机器断言的 closed-world
（G-C4D-VISIBILITY）：任一时刻至多 1 个 packet 文件 + 至多 1 个
active draft 文件，无其他文件。SEAL 完成后 active workspace 清空
（§6.4），下一 packet handoff 前 active 域为空——**active 域任何时刻
只存在当前 open REVEAL 的一个 packet**。

### 2.2 第一 packet REVEAL 后 annotator 取得什么（冻结答案，v0.1 原文保持）

**取得：且仅取得 exact C3 packet bytes 的一份拷贝。**

- packet 文件 = C1 冻结的 as-of-T blind packet（`as_of`、`evidence`
  （仅 available_date ≤ T 投影）、`price_panel`（截断于 T）、
  `opaque_case_id`、`packet_id`）；
- **不取得** identity mapping（真实 code/name ↔ opaque_case_id 永远
  selector-only；Phase C 内不存在解封机制，若未来需要属于另行设计的
  deblinding 阶段）；
- **不取得** group 标签、window_end、T 之后的一切价格/成交/市场/行业
  数据、xp_* 字段、其他任何 packet、packet 总数、"未来还有几个 T"；
- 拷贝为 O_EXCL exact-copy（SHA256 == REVEAL 事件 payload 的
  `packet_sha256`），文件名 = `<packet_id>.json`（无任何身份信息）。

### 2.3 泄漏通道清单（逐项封死）

| 通道 | 禁令 |
| --- | --- |
| annotator 域文件集合 | 任一时刻 ≤1 packet + ≤1 draft；任何额外文件（含隐藏文件、identity 片段、其他 packet、outcome/xp 工件）= G-C4D-VISIBILITY FAIL |
| 文件名 | 只允许 `<packet_id>.json` / `annotation_draft.json`；不得携带 code/name/T/group |
| sealing log / manifest / 错误信息 | production 域对 annotator 不可读；C4-D fail 信息只引用 hash 与 gate 名 |
| packet 计数 | active 域任何时刻只存在当前 open REVEAL 的一个 packet；SEAL 后清空（§6.4）；下一 packet 到达前不出现第二个 packet 文件 |
| public anchor / report | 仅 commitment hash 与 boolean（§8）；C4-C anchor 不更新 |
| draft 内容 | draft schema closed-world；`evidence_refs` 只允许指向本 packet 内可解析 JSON Pointer（§4.1），`evidence_note` 为自由文本但不做语义解析 |

### 2.4 Outcome blindness（继承 CSR-7，不因解封 packet 而开放）

```text
annotation-visible set ≠ selector-visible set ≠ outcome-visible set
```

- annotator 可见 = §2.1 annotator-visible 域 + 当前 packet 内容本身；
- outcome-visible set 在 C4-D 阶段对 annotator = **空**：SEAL 前不得出现
  任何 annotation 后未来信息（后续价格、outcome 统计、G5 primary
  stats、XP 任何内容）；
- selector 侧不得把任何 outcome 数据写入 annotator 域
  （G-C4D-VISIBILITY）；
- XP annotation session 维持独立与 BLOCKED_FOR_PIT；G5 维持 BLOCKED。

---

## 3. Annotation lifecycle（状态机，冻结；FIX2-C4 后含 finalize 分相）

```text
NO_ANNOTATION ─handoff→ ANNOTATION_OPEN ─make_receipt→ READY_TO_SEAL
                     （draft 可自由改写）                  （attempt 已原子
                                                             发布，不可变）
READY_TO_SEAL ─human seal approval→ SEAL_AUTHORIZED ─seal txn→ SEAL_COMMITTED
                                                                （链上事实已定）
SEAL_COMMITTED ─anchor durable + cleanup + POST_SEAL_FINAL→ SEALED
     └─ crash in finalize → SEALED_PENDING_FINALIZE（只补 finalize，
        绝不第二次 append SEAL）
```

**状态由 persisted 文件集合派生，不存在独立可写的 state 字段。**
派生需同时看 annotator active 域与 `c4d_receipts` 域（§4.6）：

| 状态 | 派生判据（机器） |
| --- | --- |
| NO_ANNOTATION | active 域无 packet 文件；无 attempt 目录 |
| ANNOTATION_OPEN | packet 文件存在且有效；active attempt 无 receipt |
| READY_TO_SEAL | active attempt 的 receipt 存在且 closed-world 有效且与 packet/REVEAL 事件一致；无 seal_approval |
| SEAL_AUTHORIZED | READY_TO_SEAL 判据 + seal_approval 存在且有效（approved_receipt_sha256 == SHA256(exact receipt bytes)） |
| SEAL_COMMITTED | chain 存在合法 SEAL 且 verify(check_head=True)+semantic replay PASS；finalize（anchor/cleanup）未完 |
| SEALED | SEAL_COMMITTED ∧ c4d_seal_anchor durable ∧ active workspace 已清空 ∧ POST_SEAL_FINAL（§6.3）PASS |

**active attempt 定义（F5）**：`ordinal-XXXX/` 下编号最大的
`attempt-NNNN/` 且该 attempt 无 `revocation.json`；更早 attempt 一律
`INELIGIBLE_FOR_SEAL`（receipt 与 snapshot 全部保留，永不删除）。

**各状态可变性（冻结）：**

- ANNOTATION_OPEN：active draft 自由改写；schema 只在 `make_receipt`
  时 fail-closed 校验（工作期不逐笔拦截，准入在冻结点）；
- READY_TO_SEAL：receipt 自发布起不可变；**active draft 已锁 0400
  （锁定先于 attempt 发布，§4.3 FIX3-F19 invariant：attempt 存在 ⇒
  draft 已锁且 bytes == draft_snapshot.bin）**；draft 的 exact bytes
  已快照到 selector-only `draft_snapshot.bin`（F1），
  `draft_sha256 = SHA256(draft_snapshot.bin)`
  ——语义重放从此**不依赖 annotator 工作目录存在**；作废 = 对该
  attempt 追加 `revocation.json`（§4.5），随后新 attempt 从
  ANNOTATION_OPEN 重新起草；**seal_approval 存在后禁止作废**（否则出现
  "批准 A、seal B"的语义复杂度）；
- SEAL_AUTHORIZED：只允许进入 seal transaction 或（approval 尚未被消
  费且未 SEAL 时）保持；approval 不可变、不可撤；
- SEAL_COMMITTED：链上事实已定；只允许 finalize（anchor 发布 +
  cleanup + POST_SEAL_FINAL 复验）或保持；**任何再次 SEAL append 非法**；
- SEALED：一切只读；approval 被 SEAL 不可逆消费（§6.2）。

**Exact-bytes 原则（与 C4-C no-equivalent-regeneration 同型）：**

> SEAL 事务消费的是 **exact persisted receipt bytes**。进入 seal
> transaction 之后任何一步都不得现场重新 canonicalize 一个"语义相同"
> 的对象再拿去封存——语义等价的重建物没有资格成为被 SEAL 的对象。

---

## 4. Schema 与字节身份

### 4.1 Annotation 内容契约（F8：完整闭集逐项冻结）

**hypothesis 判定结构逐项复制自 CSR-7 冻结协议
（`hypothesis_block`），不裁剪、不重定义**（v0.1 自造的
`SUPPORTED/NOT_SUPPORTED/NOT_ASSESSABLE` verdict 枚举作废，以本节为
准）：

- hypothesis 闭集（固定顺序，逐条必判，**不得删除任何一条**）：

```text
rt_H01  rt_H02  rt_H03  rt_H04  rt_H05  rt_H06
```

- 每条 judgment 为两段式（先判 observability，再判 support）：

```text
observability ∈ { OBSERVABLE, UNOBSERVABLE }          （CSR-7 冻结二档）
support       ∈ { SUPPORTED_STRONG,                    （CSR-7 冻结五档）
                  SUPPORTED_PARTIAL,
                  MIXED,
                  NOT_OBSERVED,
                  CONTRADICTED }
support presence rule: observability == OBSERVABLE ⇔ support 非空；
UNOBSERVABLE ⇒ support 留空（数据缺席 ≠ 反证，CSR 一贯原则）
```

- "无法判断"的 CSR-7-native 实现 = `UNOBSERVABLE`（不删 hypothesis、
  不新造枚举）；
- `rt_judgments` 必须：每 hypothesis 恰一条、无重复、无缺失、按上列冻
  结顺序排列；
- flags 闭集（可空、无重复）：`DATA_QUALITY_ISSUE`、
  `EVIDENCE_INCOMPLETE_AT_T`、`PACKET_PARSE_ANOMALY`、
  `FLAGGED_FOR_REVIEW`。

**annotation content contract** 以 canonical JSON 冻结，其哈希为：

```text
annotation_contract_sha256
= 5f5f01503ea255e87e784ea55da0709e5a53ff26b2b62dc9534cff46537509de
```

（contract 对象 = 上列全部枚举与规则，canonical 序列化
`json.dumps(sort_keys=True, ensure_ascii=False,
separators=(',',':'))` 后取 SHA256；实现必须内嵌同一常量并在校验
时重算比对。）

### 4.1.1 Contract exact preimage（FIX2-C1：逐字节冻结，可独立复算）

上表 hash 的**唯一 preimage** 即下面这一行 canonical JSON（UTF-8，无空
格、无换行、键按字典序）；任何人可对其逐字节复算出上表 hash：

```json
{"contract_version":"c4d-annotation-content-v1","flags_enum":["DATA_QUALITY_ISSUE","EVIDENCE_INCOMPLETE_AT_T","PACKET_PARSE_ANOMALY","FLAGGED_FOR_REVIEW"],"flags_rule":"flags may be empty; values unique; closed set","hypotheses":["rt_H01","rt_H02","rt_H03","rt_H04","rt_H05","rt_H06"],"judgment_rule":"exactly one judgment per hypothesis; order fixed as listed; none may be dropped","observability_enum":["OBSERVABLE","UNOBSERVABLE"],"source":"CSR_7_CASE_PROTOCOL.yaml hypothesis_block (frozen) — copied verbatim, not redefined","support_enum":["SUPPORTED_STRONG","SUPPORTED_PARTIAL","MIXED","NOT_OBSERVED","CONTRADICTED"],"support_presence_rule":"support present iff observability == OBSERVABLE; UNOBSERVABLE leaves support empty (data absence != disconfirmation)","unjudgeable_mapping":"CSR-7-native UNOBSERVABLE realizes 'cannot judge' — no hypothesis may be deleted"}
```

复算程序（与 C2/c4d canon 同规则）：

```text
SHA256( json.dumps(contract, sort_keys=True, ensure_ascii=False,
                   separators=(',',':')) )
```

### 4.2 Draft schema（c4d-draft-v1，closed-world）

```yaml
draft_version: c4d-draft-v1
session_id: c4-prod-0002
packet_id: <被揭示 packet 的 packet_id>
packet_sha256: <被揭示 packet 的 SHA256>
annotation_session_id: <opaque，见下>
annotation_attempt: 1            # 从 1 起；重标注递增（F5）
annotation:
  annotation_contract_sha256: 5f5f0150…509de
  rt_judgments:                  # §4.1 闭集全判，固定顺序
    - hypothesis_id: rt_H01
      observability: OBSERVABLE | UNOBSERVABLE
      support: <五档之一 | 空>
      evidence_refs:             # F10：结构化引用，0..N 条
        - /evidence/3
        - /price_panel/close
      evidence_note: <=500 chars # 自由解释文本，机器不解析语义
  overall_note: <=2000 chars
  flags: []                      # §4.1 flags 闭集
created_at: <canonical UTC>
updated_at: <canonical UTC>
```

**annotation_session_id（裁决1）**：一次独立 blind annotation session
的 opaque ID。规则：随机 opaque；handoff 前固定；**per annotation
attempt 唯一**；不跨 packet 复用；不含姓名/agent name/model/provider。
真实 human/agent/model 的对应关系如有审计需要，只存 selector-only
registry（不进 annotator 域、不进 public）。

**evidence_refs（F10）**：机器只做结构校验——每条必须是合法 JSON
Pointer 且 resolve 到当前 packet 内已存在的值；不试图解析
`evidence_note` 的自然语言。

draft 序列化在 OPEN 阶段不要求 canonical（annotator 工具自由），
`make_receipt` 从 exact draft bytes 解析并 closed-world 校验。

### 4.3 Receipt schema（c4d-receipt-v1，closed-world，一次性冻结）

```yaml
receipt_version: c4d-receipt-v1
session_id: c4-prod-0002
packet_id: <同 draft>
packet_sha256: <同 draft>
reveal_event_hash: b5ec0ba1…437d5        # 产生本 annotation 义务的 REVEAL
annotation_attempt: 1
draft_sha256: <make_receipt 时刻 exact draft bytes 的 SHA256
              == SHA256(draft_snapshot.bin)>
annotation: <draft 的 annotation 子对象，原样嵌入（含 contract sha256）>
annotation_session_id: <同 draft>
receipt_id: <opaque unique id，创建时固定>
created_at: <canonical UTC，创建时固定>
```

`make_receipt` 是唯一冻结点：读 exact draft bytes → closed-world 校验
（schema + §4.1 契约 + packet/session 绑定 + reveal_event_hash ==
production chain 最后一条 REVEAL 的 event_hash）→ 组装 → canonical 序列
化。**发布为整个 attempt 的原子事务，且 draft 锁定先于发布
（FIX3-F19：attempt 出现 ⇒ draft 已锁 0400，为 invariant）**：

```text
1. 读 exact active draft bytes D，closed-world 校验
2. staging 内构造 receipt.json（canonical，0600）与
   draft_snapshot.bin（== D，0600）
3. fsync(receipt.json)、fsync(draft_snapshot.bin)、fsync(staging dir)
4. active draft chmod 0400（锁）
5. reread active draft：必须仍 exact == D（否则 HALT——内容在锁定
   竞争中被改写）
6. fsync(active draft) + fsync(active draft parent)
7. renameat2(RENAME_NOREPLACE) attempt-NNNN.staging → attempt-NNNN/
8. fsync(ordinal-XXXX/)
```

**crash 恢复（严格定义，不新增长期状态）：**

- crash 在 1–3（draft 未锁）：只留 `*.staging/`（uncommitted，等同
  C4-C `sealing.staging` 的 disposable 地位）→ 清 staging → 状态仍
  ANNOTATION_OPEN；
- crash 在 4–6 之后、7 之前（draft 已锁 0400，attempt 未发布）：
  清 disposable staging → 确认不存在 committed attempt →
  **chmod draft 回 0600 + fsync** → ANNOTATION_OPEN（无 half-READY）；
- attempt 已存在（7 之后）：draft **必须**为 0400 且 bytes ==
  draft_snapshot.bin——若 mode/content 漂移，属 contract drift /
  tamper，**FORENSIC，不得静默修正**（G-C4D-SEAL-PREFLIGHT，即 D22
  的确定语义）。

attempt 目录一旦出现即完整含 receipt+snapshot 且对应 draft 已锁——
不存在"有 receipt 无 snapshot"或"READY 但 draft 可写"的半状态。
receipt 与 snapshot 均不可变（重建/改写 = G-C4D-RECEIPT FAIL）。
`seal_approval.json` / `revocation.json` 随后以单文件 O_EXCL 追加进已
发布的 attempt 目录（各自原子，无需 staging）。

### 4.4 SEAL approval authority（F4，c4d-seal-approval-v1，closed-world）

```yaml
approval_version: c4d-seal-approval-v1
scope: SEAL_ANNOTATION_ONLY
session_id: c4-prod-0002
reveal_event_hash: <r1>
annotation_attempt: 1
approved_receipt_sha256: <exact receipt hash>
approved: true
created_at: <canonical UTC>
```

- 路径：`c4d_receipts/<session>/ordinal-XXXX/attempt-NNNN/seal_approval.json`，
  O_EXCL、0600；
- 创建条件：该 attempt 处于 READY_TO_SEAL 且无 revocation；
- **这是"人工确认 seal 该 exact receipt hash"的机器化持久**：人类批准
  落盘后，crash/restart 仍能从 persisted state 证明用户批准过什么；
- 不可变、不可撤、不可重复（O_EXCL）；
- **消费语义**：`consumed ⇔ semantic replay 证明存在合法 SEAL exact
  绑定 approved_receipt_sha256`（§6.2）；SEAL 事件即对这次 approval
  的不可逆消费。

### 4.5 Receipt revocation（F5，append-only tombstone）

```yaml
revocation_version: c4d-receipt-revocation-v1
session_id: c4-prod-0002
reveal_event_hash: <r1>
annotation_attempt: 1
receipt_sha256: <被作废 receipt 的 exact hash>
reason_code: DRAFT_ERROR | BINDING_ERROR | ANNOTATOR_REQUEST | OTHER
created_at: <canonical UTC>
```

- 路径：同 attempt 目录下 `revocation.json`，O_EXCL、0600；
- 效果：该 attempt 永久 `INELIGIBLE_FOR_SEAL`；receipt 与
  draft_snapshot **保留不删**（immutable-object 原则）；
- **禁止条件**：同 attempt 已有 `seal_approval.json` 时创建 revocation
  = G-C4D-RECEIPT FAIL（裁决3：不允许"批准后作废换 B"）；
- 新 attempt = 当前最大 attempt + 1，回到 ANNOTATION_OPEN 重新起草。

### 4.6 Selector-only 控制域（F1）

```text
data/csr8_phase_c/c4d_receipts/                  （gitignored，0700）
└── c4-prod-0002/
    └── ordinal-0001/                            （本 packet 的 REVEAL 序数）
        ├── attempt-NNNN.staging/                （仅 crash 残留；disposable）
        ├── attempt-0001/                        （RENAME_NOREPLACE 原子发布）
        │   ├── receipt.json                     （0600，不可变）
        │   ├── draft_snapshot.bin               （exact draft bytes 快照）
        │   ├── seal_approval.json               （§4.4，可有可无）
        │   └── revocation.json                  （§4.5，可有可无）
        └── attempt-0002/…                       （仅重标注时存在）
```

目录 0700、文件 0600、全部 O_EXCL。语义重放只依赖本域 + production
chain，**不依赖 annotator active workspace 存续**（裁决4 的前提）。

### 4.7 三层字节身份（更正 v0.1 §6.1 的字段名错误）

receipt schema **没有** `receipt_sha256` 字段；正确表达：

```text
draft_sha256（记入 receipt）= SHA256(exact draft_snapshot.bin bytes)
SHA256(exact persisted receipt bytes)
  == SEAL event.payload.receipt_sha256
  == SHA256(C2 archived bytes/seal_annotation/<seq>.bin)
```

---

## 5. SEAL transaction（crash-safe，in-place append）

### 5.1 与 C4-C publication 的差异（v0.1 论证保持）

sealing 目录已在位、承载 durable REVEAL，整目录 staging+rename 会触碰
已提交事实——禁止。SEAL 采用**冻结 C2 API 的 in-place append + 事务级
fsync closure + 链导出 recovery**。C2 一字不改，其 trust model（head
anchor mandatory）不被重定义。

### 5.2 冻结执行顺序

```text
(1)  production verify()（check_head=True）PASS；chain == [REVEAL r1]
(2)  语义前置：active attempt 状态 == SEAL_AUTHORIZED
     （receipt 有效且绑定 r1；approval 有效且
      approved_receipt_sha256 == SHA256(exact receipt bytes)；
      无 revocation；SEAL 数 == 0）
(3)  SEAL payload（仅此三字段 + C2 自动 bytes_ref）：
       {opaque_case_id, T, receipt_sha256}      # 取自 r1 payload / receipt
     content_bytes = exact persisted receipt bytes
(4)  C2 append SEAL（pre-write exact-byte gate；写入
     bytes/seal_annotation/<seq>.bin；追加事件行；重写 head）
(5)  事务级 fsync closure：bytes 文件、log、head、sealing 目录逐一 fsync
(6)  production verify()（check_head=True）全链重放 PASS
(7)  C4-D semantic replay（§6.1，对 exact receipt）PASS
     —— 至此 **SEAL_COMMITTED**（链上事实已定；此后任何失败都不得
     再次 append SEAL）
(8)  c4d_seal_anchor.json 原子发布（publish_anchor_durable 语义，§8）
(9)  active annotator workspace 清空（§6.4）
(10) POST_SEAL_FINAL 校验（§6.3，含 workspace 已清空）PASS
     —— 至此 **SEALED**
(11) HARD STOP（第二 packet 权限另起，§7）
```

(8)–(10) 为 finalize 阶段：任一步 crash 进入 `SEALED_PENDING_FINALIZE`
（§5.3），恢复**只允许补 anchor / cleanup**，绝不允许第二次 SEAL append。

### 5.3 Recovery matrix（F2/F3；核心语义冻结）

> **trusted head = committed prefix；unanchored log tail ≠ committed
> event。** head 不是 cache——删除"head 是 cache"的一切表述。恢复只允
> 许把**唯一可证明的一个 SEAL tail** 完成提交。

恢复时逐行扫描 log：`N` = trusted head 的 count；前 N 行必须构成可从
genesis 验证的完整链且末 event_hash == trusted head_hash（trusted
prefix 证明）。

| 链上事实 | 判定 | 恢复动作 |
| --- | --- | --- |
| 前 N 行 == trusted prefix；无第 N+1 行；`bytes/seal_annotation/<N>.bin` 存在但无事件引用，且 `SHA256(orphan bytes)` == `SHA256(persisted receipt)` == `approved_receipt_sha256` | **MATCHED_ORPHAN**（本事务自身的未竟写入） | READY/SEAL_AUTHORIZED 保持；受控 retry（append 重写同 seq 确定性路径） |
| 前 N 行 == trusted prefix；无第 N+1 行；孤儿 bytes 存在但 hash 不匹配上述三方 | **FOREIGN_ORPHAN** | FORENSIC：HALT，**禁止覆盖/删除该 bytes**，禁止 retry |
| 前 N 行 == trusted prefix；恰有第 N+1 **完整** 行，且 candidate 满足下述全部条件 | `SEAL_TAIL_UNANCHORED`（**不得记作 SEALED**） | 按严格条件完成提交（下） |
| 前 N 行 == trusted prefix；其后 suffix 为 malformed/不完整 JSON 行 | `SEAL_TAIL_PARTIAL`（uncommitted tail） | 截断回 trusted-head byte boundary（即第 N 行行尾字节偏移）→ fsync(log) → 残留 `bytes/seal_annotation/<N>.bin` 按**上述 MATCHED/FOREIGN 判据**处理（MATCHED 可 retry；FORENSIC 不得动） → 状态保持 READY/SEAL_AUTHORIZED |
| 链含合法 SEAL 且 verify(check_head=True) PASS，但 c4d anchor 缺失/陈旧，或 active workspace 未清空 | `SEALED_PENDING_FINALIZE`（FIX2-C4） | **只允许** publish_anchor_durable 补 anchor + cleanup workspace + POST_SEAL_FINAL 复验；**绝不再次 append SEAL** |
| 全链含 SEAL 且 verify(check_head=True) PASS 且 finalize 完成 | SEALED | 只读；semantic replay 复证 |
| 其他（trusted prefix 不成立 / 多余 tail / foreign bytes / 验证失败） | SEAL_FORENSIC | HALT，禁止 retry |

**`SEAL_TAIL_UNANCHORED` 完成提交的严格条件（全部成立才允许
sync_head）：**

```text
trusted old head  = count 1 = head_hash r1.event_hash
raw log           = 恰比 trusted prefix 多 1 条完整事件行
candidate event   : sequence_no = 1
                    type = SEAL_ANNOTATION
                    prev_event_hash = r1.event_hash
archived receipt bytes = exact persisted receipt bytes（hash 相等）
candidate 全链 verify(check_head=False) PASS
C4-D semantic replay（§6，对 exact receipt）PASS
不存在任何额外 event / 额外 tail / foreign bytes
        ↓
sync_head(candidate chain) → fsync(head) → fsync(sealing dir)
→ verify(check_head=True) PASS → semantic replay PASS
        ↓
SEAL_COMMITTED                    （FIX3-F18：终态是 COMMITTED，不是 SEALED）
        ↓
c4d anchor durable → workspace cleanup → POST_SEAL_FINAL
        ↓
SEALED
```

截断只允许删除**不属于任何 committed event 的字节**（第 N 行行尾之后
的 uncommitted tail），且仅当 trusted prefix 完整验证成立——这是对
"append 从未提交"的恢复，不是对 production 历史的改写。

---

## 6. 语义层：persisted semantic replay + final invariant

### 6.1 G-C4D-SEAL-REPLAY（每次事务后与恢复时强制）

全部从盘上对象派生（annotator active workspace 不在依赖内）：

```text
SHA256(exact persisted receipt bytes)
  == SEAL event.payload.receipt_sha256
  == SHA256(archived bytes/seal_annotation/<seq>.bin)      （三方一致）

receipt.reveal_event_hash == r1.event_hash
receipt.packet_id / packet_sha256 == r1.payload 同名字段
receipt.draft_sha256 == SHA256(draft_snapshot.bin)          （快照一致）
seal_approval.approved_receipt_sha256 == SHA256(exact receipt bytes)
SEAL.payload.opaque_case_id / T == r1.payload 同名字段      （C2 已证闭包）
annotation contract == §4.1 冻结契约（annotation_contract_sha256 比对）
annotator active 域文件集合 == closed-world 期望集合
```

任何一方不一致 ⇒ G-C4D-SEAL-REPLAY FAIL（fail-closed，HALT）。

### 6.2 SEAL_COMMITTED 的机器定义 + approval 消费

```text
first packet SEAL_COMMITTED :=
    production chain 存在 REVEAL r1（绑定 session c4-prod-0002）
  ∧ 存在 exact persisted receipt artifact（§4.3 有效、无 revocation）
  ∧ 存在合法 seal_approval（§4.4）
  ∧ 存在合法 SEAL s1（C2 全链重放 PASS：闭包、无重复、exact-byte）
  ∧ persisted semantic replay（§6.1）证明 r1→s1 配对
  ∧ s1 exact 绑定 approved_receipt_sha256（approval 被消费）

SEALED := SEAL_COMMITTED
  ∧ c4d_seal_anchor.json durable（§8）
  ∧ active annotator workspace 已清空（§6.4）
  ∧ POST_SEAL_FINAL（§6.3）PASS
```

§7.1 的第二 packet 前置以 **SEALED**（完整 finalize 后）为准；
`SEALED_PENDING_FINALIZE` 期间不得生成 ordinal-2 proposal。

### 6.3 POST_SEAL_FINAL invariant（FIX2-C4：仅在 cleanup 之后校验）

```text
PRODUCTION_EVENT_COUNT == 2 且事件序 == [REVEAL_PACKET, SEAL_ANNOTATION]
sealed_count == 1；open_reveals == ∅
active attempt 的 receipt/approval 语义一致；历史 attempt（若有）均
  INELIGIBLE_FOR_SEAL 且未被 SEAL
annotator active 域已清空（§6.4）
911d8b84…5dc81 仍为 CONSUMED；c4c_anchor.json 原字节不变
```

### 6.4 Post-SEAL workspace cleanup（裁决6/F6）

SEAL semantic replay + `c4d_seal_anchor.json` durable 之后：

```text
active packet 文件   → remove
active draft 文件   → remove   （exact bytes 已存 draft_snapshot.bin）
```

审计能力不受损：exact packet 已在 C3 frozen 池 +
`bytes/reveal_packet/0.bin`；exact frozen draft 在
`draft_snapshot.bin`。下一 packet handoff 时 active 域重新恰含一个
packet（§2.3 计数规则保持）。

---

## 7. 第二 packet reveal prerequisite + ordinal 授权链

### 7.1 强前置条件（冻结）

```text
first packet SEALED（§6.2 机器定义成立）
  ⇒ 才允许为 ordinal-2 candidate 生成新的 pre-authorization proposal
```

C2 strict alternation 是链层底线；C4-D 在授权层再加一道：前置不满足
时 ordinal-2 proposal 创建即 G-C4D-AUTHZ FAIL。

### 7.2 ordinal/session-bound 授权 schema（c4d-reveal-v1，全新）

```yaml
authorization_version: c4d-reveal-v1          # 不复用 c4c-auth-v1
scope: NEXT_REVEAL_ONLY                       # 新 scope 字符串
reveal_ordinal: 2                             # 显式序数
session_id: c4-prod-0002
sealed_prefix_head: <SEAL s1 后的 production head hash>
c3_manifest_commitment: 883c9869…d0b
candidate_packet_id: <candidate_for_ordinal(2) 的 packet_id>
candidate_packet_sha256: <同上 exact hash>
authorized: true
authorization_id: <opaque，proposal 时固定>
created_at: <canonical UTC，proposal 时固定>
```

三段式流程与 C4-C 同构，沿用其冻结 materializer 语义（权限契约 +
closed-world + canonical bytes + frozen candidate binding + O_EXCL +
exact-copy permit + fsync）。旧授权 `911d8b84…5dc81` 属
`c4c-auth-v1 / FIRST_REVEAL_ONLY`，在新 schema 下四重不匹配
（版本/scope/序数/前缀绑定）= G-C4D-AUTHZ FAIL。

**Persisted protocol（FIX2-C5 + FIX3-F17：路径/schema/权限契约逐项冻结）**——
proposal 含 candidate_packet_id/sha256、sealed_prefix_head、reveal_ordinal
等下一 packet identity，**必须 selector-only**；整条路径链 0700、文件
0600（替代 v0.3 的 0644——0644 无法机器证明 proposal 对 annotator 不可
见，违反 §2.3/blindness 契约）：

```text
proposal（外部域，对 production 只读；FIX3-F17 selector-only）
  data/csr8_phase_c/c4d_proposals/       0700
  └── c4-prod-0002/                      0700
      └── ordinal-000N/                  0700
          └── next_reveal.proposal.json  0600
                                        canonical，O_EXCL，
                                        fsync(file + parent)，gitignored

approval（human exact-hash 批准的机器化持久；production 域首个新写）
  data/csr8_phase_c/production/c4-prod-0002/authorization/ordinal-000N/
    next_reveal.approval.json            canonical，0600，O_EXCL，fsync
                                        file+parent；目录 0700

permit（approval 的 exact-copy 物化，事务唯一入口）
  …/authorization/ordinal-000N/next_reveal.permit.json
                                        bytes == approved proposal bytes，
                                        0600，O_EXCL
```

human UI 仍然只输出 `proposal_sha256`（§7.4）；annotator 任何时点不可
读 c4d_proposals / authorization 域（G-C4D-AUTHZ + G-C4D-VISIBILITY，
fixture D46 证之）。

approval schema（c4d-reveal-approval-v1，closed-world）：

```yaml
approval_version: c4d-reveal-approval-v1
scope: NEXT_REVEAL_ONLY
session_id: c4-prod-0002
reveal_ordinal: N
sealed_prefix_head: <与 proposal 一致>
approved_authorization_sha256: <approved proposal exact hash>
approved: true
created_at: <canonical UTC>
```

约束：approval 只在 proposal bytes 与 persisted approval 精确一致时可
创建；permit 是 approved proposal bytes 的 exact copy（无重新
canonicalization）；三者任一 hash 不一致 = G-C4D-AUTHZ FAIL。**C4-C 的
`first_reveal.*` authorization 文件为冻结事实，永不触碰。**

### 7.2.1 REVEAL payload 扩展（链导出消费证明，FIX2-C5）

ordinal-2+ 的 `REVEAL_PACKET` payload 在 C1 字段之外**必须**绑定新授权
（closed-world；ordinal-1 保持已提交的 `b5ec0ba1…` 原样不动）：

```yaml
opaque_case_id: <candidate_for_ordinal(N)>
T: <同上>
packet_id: <SHA256(opaque_case_id|T)>
packet_sha256: <exact packet bytes hash>
session_id: c4-prod-0002
reveal_ordinal: N                       # 新增
authorization_id: <proposal 时固定>     # 新增
authorization_sha256: <proposal hash>   # 新增
sealed_prefix_head: <与 proposal 一致>  # 新增
c3_manifest_commitment: 883c9869…d0b    # 新增
candidate_packet_sha256: <与 proposal 一致>  # 新增
# bytes_ref 由 C2 append 自动附加
```

链导出消费定义（与 C4-C derive_consumption 同型）：

```text
authorization(N) CONSUMED ⇔ production chain 存在 REVEAL r_N 满足
    r_N.payload.authorization_id        == proposal.authorization_id
  ∧ r_N.payload.authorization_sha256    == approved_authorization_sha256
  ∧ r_N.payload.sealed_prefix_head      == proposal.sealed_prefix_head
  ∧ r_N.payload.c3_manifest_commitment  == proposal.c3_manifest_commitment
  ∧ r_N.payload.candidate_packet_sha256 == proposal.candidate_packet_sha256
  ∧ r_N.payload.reveal_ordinal          == N
```

无链上匹配 = UNUSED；permit 存在但链字段不一致 = UNRESOLVABLE →
FORENSIC；匹配到别的 ordinal/session = FOREIGN → FORENSIC。

### 7.3 candidate_for_ordinal(n)（F7：确定性全序，冻结）

C4-A 冻结的 `first_candidate()` 只定义了 ordinal-1。C4-D 新冻结 total
order（并保证 ordinal-1 与 C4-C 完全一致）：

```text
case_rank  = 既有 C4-FIRST-v1 顺序：HMAC(C4-FIRST-v1 | ocid) 字典序，
             ocid tie-break（逐 case 唯一）
每 case 的 eligible T_list = 该 case 全部 eligible T 升序
             （eligible = 冻结 eligibility 轴上 PACKET_GENERATION_ALLOWED；
             G5 PROVISIONAL_BLOCKED 案例整体排除）
T_rank     = T_list 内下标 0,1,2,…

global candidate key = (T_rank, case_rank)      # round-robin

全序 = 所有 (case, T) 按 (T_rank, case_rank) 字典序排列
candidate_for_ordinal(n) = 全序第 n 个元素（1-based）
```

性质（全部机器 Gate 化）：

```text
G-C4D-CAND-1  ordinal-1 == 既有 first_candidate_record（逐字段相等）
G-C4D-CAND-2  同一 (ocid,T) 在全序中恰出现一次（无重复 packet）
G-C4D-CAND-3  revealed 集合 == 全序前 k 个元素（序数即位置；任何
              跳号/乱序 = G-C4D-AUTHZ FAIL）
G-C4D-CAND-4  确定性：同一冻结 C3 状态重算任意多次结果逐字节一致
```

round-robin 的效果：不会出现同一 case 连续把所有 T 标完，更适合
blinded progressive annotation；且 ordinal-1 不变。

### 7.4 人工授权文案（裁决5，固定）

用户**只看到 `proposal_sha256`**。不显示 packet_id / T / ocid / group /
sealed_prefix / candidate rank。批准措辞固定为：

> 我明确批准 NEXT_REVEAL_ONLY proposal exact hash:
> `<64 hex>`
> 该批准仅授权 proposal 内绑定的一个 reveal ordinal，
> 不得用于其他 ordinal / packet / prefix。

机器 proposal 自身承担 reveal_ordinal / sealed_prefix_head /
candidate id/hash / session / C3 commitment，human UI 不需要看到这些
selector-only 内容。每一次 REVEAL 都需要新的独立人工批准，不存在批量
预授权。

---

## 8. Public surface（F9：独立 anchor，commitments/booleans only）

**`c4c_anchor.json` 原字节永不改动**（C4-C 冻结事实）。SEAL 后新增：

```text
output/research/csr/08_pilot_cases/phase_c/c4_public/c4d_seal_anchor.json
```

```json
{
  "production_head_hash": "<SEAL 后 head>",
  "seal_receipt_sha256": "<receipt_sha256（annotation 内容 commitment）>",
  "sealed_count": 1,
  "experiment_started": true
}
```

不暴露：packet identity、code/name/T/group、annotation 内容、下一
packet identity、packet 总数。synthetic report 同样只含 gate 名/
boolean/计数。写入沿用 publish_anchor_durable 原子语义
（missing/malformed/stale → 同目录 temp → fsync → os.replace →
fsync(parent) → reread）。

---

## 9. Synthetic / negative design gates（v0.3 冻结清单）

沿 C4-C 纪律：target-aware fixture——preparation 必须成功，只有命中
**指定 gate** 的失败才算 PASS；materialization 类 fixture 显式断言目标
对象缺席/不可变。

| # | fixture | 构造 | 目标 gate |
| --- | --- | --- | --- |
| D01 | identity leak | annotator 域被塞入 identity 片段文件 | G-C4D-VISIBILITY |
| D02 | packet count leak | active 域出现第二个 packet 文件 | G-C4D-VISIBILITY |
| D03 | outcome leak | annotator 域被塞入 outcome/xp 工件 | G-C4D-VISIBILITY |
| D04 | handoff sha mismatch | 拷贝 packet bytes ≠ REVEAL payload packet_sha256 | G-C4D-HANDOFF |
| D05 | duplicate handoff | packet 文件已存在再 handoff | G-C4D-HANDOFF（O_EXCL） |
| D06 | draft extra field | closed-world 外字段 | G-C4D-DRAFT |
| D07 | draft missing field | 缺必填字段 | G-C4D-DRAFT |
| D08 | hypothesis 缺失/重复/乱序 | rt_judgments 违反 §4.1 全判+顺序 | G-C4D-DRAFT |
| D09 | observability/support 违例 | UNOBSERVABLE 带支持度 / OBSERVABLE 空支持度 / 枚举外值 | G-C4D-DRAFT |
| D10 | contract drift | annotation_contract_sha256 ≠ 冻结常量 | G-C4D-DRAFT |
| D11 | evidence_refs 不可解析 | JSON Pointer 非法或 resolve 失败 | G-C4D-DRAFT |
| D12 | receipt wrong packet | 自洽 receipt 但 packet_id 错 | G-C4D-RECEIPT |
| D13 | receipt wrong session | session_id 错 | G-C4D-RECEIPT |
| D14 | receipt wrong reveal | reveal_event_hash ≠ 链上最后 REVEAL | G-C4D-RECEIPT |
| D15 | receipt noncanonical | 持久化 bytes ≠ canon(json) 且下游引用与其自洽（陷阱） | G-C4D-RECEIPT |
| D16 | receipt rewrite | 已有 receipt 再 O_EXCL/改写 | G-C4D-RECEIPT |
| D17 | snapshot 不一致 | draft_snapshot.bin ≠ draft_sha256 | G-C4D-RECEIPT |
| D18 | revoked receipt 入 seal | attempt 已有 revocation 仍尝试 make_approval/SEAL | G-C4D-RECEIPT |
| D19 | approval 后作废 | seal_approval 存在时创建 revocation | G-C4D-RECEIPT |
| D20 | approval hash mismatch | approved_receipt_sha256 ≠ SHA256(receipt bytes) 时 SEAL | G-C4D-SEAL-PREFLIGHT |
| D21 | duplicate approval | seal_approval 已存在再创建 | G-C4D-RECEIPT（O_EXCL） |
| D22 | draft drift post-freeze | published attempt 存在但 active draft mode≠0400 或 bytes≠draft_snapshot（FORENSIC 不静默修正） | G-C4D-SEAL-PREFLIGHT |
| D23 | SEAL hash mismatch | payload receipt_sha256 ≠ 归档 bytes SHA256 | C2 delegated（exact-byte） |
| D24 | SEAL without REVEAL | 空/外来链上先 SEAL | C2 delegated |
| D25 | double SEAL | 对同一 (ocid,T) 二次 SEAL | C2 delegated |
| D26 | second REVEAL before SEAL | r1 未 SEAL 即尝试 r2 | C2 alternation + G-C4D-BOUNDARY |
| D27 | reused authorization | c4c-auth-v1/FIRST_REVEAL_ONLY 结构申请 ordinal-2 | G-C4D-AUTHZ |
| D28 | wrong sealed_prefix | ordinal-2 proposal 的 sealed_prefix_head 错/缺 | G-C4D-AUTHZ |
| D29 | ordinal 前置不满足 | r1 未 SEAL 时构造 ordinal-2 proposal | G-C4D-AUTHZ（§7.1） |
| D30 | candidate ordinal-1 漂移 | 全序重算的 #1 ≠ first_candidate_record | G-C4D-CAND-1 |
| D31 | candidate 重复/乱序 | 全序含重复 (ocid,T)；revealed ≠ 前缀 | G-C4D-CAND-2/3 |
| D32 | malformed persisted chain | production log 篡改后 SEAL/恢复 | G-C4C-PROD-REPLAY delegated |
| D33 | semantic three-way break | receipt/归档 bytes/event hash 任一方单独篡改（其余自洽） | G-C4D-SEAL-REPLAY |
| D34 | crash: matched orphan | bytes 写入后无事件行且三方 hash 匹配 → MATCHED_ORPHAN → retry 成功且恰 2 events | recovery assertion |
| D35 | crash: partial JSONL tail | 半行写入 → 截断回 trusted-head boundary → 状态保持 → retry | recovery assertion |
| D36 | crash: unanchored tail | 完整 SEAL 行 + head 未重写 → 严格条件完成提交 → SEAL_COMMITTED；并证伪"head 是 cache"表述（任何条件不满足即 FORENSIC） | recovery assertion |
| D37 | attempt-2 正向流 | attempt-1 作废 → attempt-2 全流程 PASS；attempt-1 artifact 保留且 INELIGIBLE | positive proof |
| D38 | SEALED 后清理 | cleanup 后 active 域恰空；semantic replay 仍 PASS（不依赖 workspace） | cleanup assertion |
| D39 | C4-C anchor 不可变 | SEAL 流程任何一步后 c4c_anchor.json 字节不变 | G-C4D-BOUNDARY |
| D40 | foreign orphan | 孤儿 bytes hash ≠ receipt/approval 三方 → FORENSIC，bytes 原样未动，禁止 retry/覆盖 | recovery assertion（FIX2-C2） |
| D41 | attempt 发布 crash（两窗口） | (a) staging 半途（receipt 有 snapshot 无）→ 不产生 half-READY；(b) draft 已锁 0400 + staging 未 rename（FIX3-F19）→ 清 staging → 确认无 committed attempt → draft chmod 回 0600 → ANNOTATION_OPEN → 重做 make_receipt PASS | recovery assertion（FIX2-C3 + FIX3-F19） |
| D42 | SEAL committed / anchor missing | 链上 SEAL 完整、c4d anchor 缺失 → SEALED_PENDING_FINALIZE → 仅 finalize（anchor+cleanup+复验），第二次 append SEAL 被拒 | recovery assertion（FIX2-C4） |
| D43 | anchor durable / workspace 未清 | cleanup 前 crash → finalize-only 恢复补 cleanup；期间 ordinal-2 proposal 被拒（前置=SEALED 非 COMMITTED） | recovery assertion（FIX2-C4） |
| D44 | ordinal-N 路径/schema 违例 | proposal/approval/permit 路径错、schema 多/缺字段、permit 非 exact-copy、权限位错 | G-C4D-AUTHZ（FIX2-C5） |
| D45 | ordinal-2 绑定断裂 | REVEAL payload 的 authorization/sealed_prefix/candidate 字段任一与 permit 不一致（其余自洽） | G-C4D-AUTHZ + G-C4D-SEAL-REPLAY delegated（FIX2-C5） |
| D46 | proposal 域权限漂移 | c4d_proposals 任一层目录非 0700 / proposal 非 0600（如 0644/0755）→ FAIL 且 approval/permit 均 ABSENT | G-C4D-AUTHZ + G-C4D-VISIBILITY（FIX3-F17） |

另保留 C4-C 全部既有 fixtures 作为回归（live-chain 断言在 C4-D 实现期
升级为：恰 1 REVEAL（SEAL 后 2）+ 双 anchor 一致 + 各域 fingerprint
不变）。

---

## 10. 权限边界（本设计阶段）

本文件不授权任何执行。设计冻结后仍需逐级放行：

```text
C4-D DESIGN FINAL FROZEN（用户）
  → C4-D synthetic implementation + synthetic audit（sandbox only，
    不碰 production、不建真实 annotator/c4d_receipts 域）
  → C4-D SYNTHETIC FINAL FROZEN（用户）
  → 真实 annotator handoff（production 零变更；仅创建 annotator 域）
  → 真实 annotation draft（标注 session）
  → 真实 receipt（机器冻结点，含 draft_snapshot）
  → 人工确认 seal 该 exact receipt_sha256（→ seal_approval 落盘）
  → SEAL transaction（一次）→ semantic replay → SEAL_COMMITTED
  → c4d_seal_anchor durable → workspace cleanup
  → POST_SEAL_FINAL → SEALED → HARD STOP
```

设计冻结前禁止：创建 annotator/c4d_receipts 域、handoff、draft/
receipt/revocation/seal_approval、SEAL、第二 packet proposal/授权、任
何 production 变更、C4-C executor 与 c4c_anchor.json 的任何改动。

---

## 11. 裁决记录（v0.1 五项开放问题已全部解决）

| 开放问题 | 裁决 | 落点 |
| --- | --- | --- |
| annotator 身份语义 | `annotation_session_id`：session identity，非 person identity；opaque、per-attempt 唯一、不跨 packet 复用；真实身份映射只存 selector-only registry | §4.2 |
| hypothesis 闭集 | 完整 CSR-7 冻结集（rt_H01..H06 + observability/support 双段），不裁剪；"无法判断"= UNOBSERVABLE；contract 哈希冻结 | §4.1 |
| receipt 作废 | append-only tombstone，receipt 永不删除；approval 存在后禁止作废 | §4.5 |
| SEAL 后 packet 保留 | active workspace 清空；审计由 C3 池 + C2 归档 + draft_snapshot 承担 | §6.4 |
| ordinal-2 授权文案 | 仅 proposal_sha256，措辞固定 | §7.4 |

v0.2 无新增开放问题。
