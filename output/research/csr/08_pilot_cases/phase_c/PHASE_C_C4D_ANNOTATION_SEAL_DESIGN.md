# CSR-8 Phase C4-D — First Annotation + SEAL Protocol Design

- 状态：DESIGN DRAFT v0.1，待用户审计；本文件不授权、不实现、不创建任何
  production 对象、不创建 annotator 域、不产生任何 production event
- 基线（全部已冻结）：
  - C2 seal log FINAL FROZEN @ `9d19be7`（`REVEAL_PACKET` / `SEAL_ANNOTATION`
    事件语义、exact-byte binding、strict REVEAL→SEAL 交替、head anchor
    mandatory）
  - C1 packet FINAL FROZEN @ `9292d0d`；C3 preflight FINAL FROZEN @
    `04f54e1`（commitment
    `883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b`）
  - C4 DESIGN v1.0 FINAL FROZEN @ `6fa5380`；C4-A/B FINAL FROZEN @ `4482e54`
  - C4-C 设计 FINAL FROZEN @ `4d9d29c`；SYNTHETIC FINAL FROZEN @ `aa04403`；
    FIRST REVEAL COMMITTED @ `54efaf5`；EXEC-RECOVERY FINAL FROZEN @
    `1d9ba55`
  - CSR-7 case protocol（annotation blindness contract、progressive
    sealing、rt_blind_packet 约束——本设计继承，不重定义标注学语义）
- 设计阶段必须保持的状态：

```text
PRODUCTION_EVENT_COUNT = 1   （exactly one REVEAL_PACKET）
production_head_hash   = b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5
authorization          = 911d8b84…5dc81 = CONSUMED（不再承担任何后续意义）
SEAL                   = 0
annotation             = 0   （annotator 域尚不存在）
outcome                = 0
G5                     = BLOCKED
XP                     = BLOCKED_FOR_PIT
experiment             = STARTED
HARD_STOP              = active（等待 C4-D 设计冻结 + 逐步人工授权）
```

本阶段唯一交付物是本设计文档。不实现任何 C4-D 代码，不创建 annotation
draft/receipt，不执行 SEAL，不发起第二 packet reveal，不修改
`c4-prod-0002` 与已冻结的 C4-C executor。

---

## 1. 设计范围与不动点

C4-D 回答四个问题：

1. 第一 packet 已经 REVEAL 后，annotator 究竟取得什么（可见性边界）；
2. annotation 从草稿到 SEALED 的生命周期与字节身份；
3. SEAL 事务如何把 exact annotation bytes 绑进 C2 hash chain（含 crash
   recovery）；
4. 第二 packet 在什么条件下才重新获得 reveal 权限（ordinal 授权链）。

**不动点（本设计与后续一切 C4-D 实现不得触碰）：**

- 冻结 C2 `csr8_phase_c_seal.py` 的事件语义一字不改；C4-D 只以调用者身份
  使用其 `append / verify(check_head) / read_events / sync_head` API；
- 已冻结的 C4-C executor（`csr8_phase_c_first_reveal.py`）语义不改——其
  SEAL/annotation 禁止 gate 在 C4-D 实现阶段由 C4-D 自己的入口接管，
  C4-C 入口保持只读/幂等；
- live production chain 恰一条 REVEAL_PACKET（event_hash
  `b5ec0ba1…437d5`）；任何 C4-D synthetic 测试只碰 sandbox，不碰
  production；
- `911d8b84…5dc81` 已消费。C4-D 的一切新授权使用新 schema、新 scope、
  新 hash（§7）。

---

## 2. 可见性三分域（annotator visibility / reveal boundary）

### 2.1 三域定义

```text
selector-only     data/csr8_phase_c/secret/            （salt、packet_plan、
                                                       真实 code↔ocid 映射）
                  data/csr8_phase_c/production/        （sealing chain、
                                                       authorization）
                  data/csr8_phase_c/c3_preflight/      （全部 packet 池）
                  data/csr8_phase_c/c4c_proposals/     （历史 proposal 域）

annotator-visible data/csr8_phase_c/annotator/c4-prod-0002/
                  ├── packet/<packet_id>.json          （exact bytes copy，
                  │                                    恰一个文件）
                  └── draft/annotation_draft.json      （annotator 工作区，
                                                       READY 前可改写）

public            output/research/csr/08_pilot_cases/phase_c/c4_public/
                  （commitments/booleans only，§8）
```

annotator 域整体 0700/0600、gitignore（与 selector-only 同级隔离，绝不
入库）。annotator 域内**禁止出现上列 annotator-visible 集合之外的任何文
件**——域内文件集合是机器断言的 closed-world（G-C4D-VISIBILITY）。

### 2.2 第一 packet REVEAL 后 annotator 取得什么（冻结答案）

**取得：且仅取得 exact C3 packet bytes 的一份拷贝。**

- packet 文件本身 = C1 冻结的 as-of-T blind packet（`as_of`、
  `evidence`（仅 available_date ≤ T 投影）、`price_panel`（截断于 T）、
  `opaque_case_id`、`packet_id`）；
- **不取得** identity mapping（真实 code/name ↔ opaque_case_id 永远
  selector-only；Phase C 内不存在解封机制，若未来需要属于另行设计的
  deblinding 阶段）；
- **不取得** group 标签、window_end、T 之后的一切价格/成交/市场/行业数
  据、xp_* 字段、其他任何 packet、packet 总数、"未来还有几个 T"；
- 拷贝为 O_EXCL exact-copy（SHA256 == REVEAL 事件 payload 的
  `packet_sha256`），文件名 = `<packet_id>.json`（无任何身份信息）。

### 2.3 泄漏通道清单（逐项封死）

code/name/T-group 不得经以下通道旁路泄漏到 annotator-visible 或
public：

| 通道 | 禁令 |
| --- | --- |
| annotator 域文件集合 | 恰 1 个 packet 文件 + ≤1 个 draft 文件；任何额外文件（含隐藏文件、identity 片段、其他 packet）= G-C4D-VISIBILITY FAIL |
| 文件名 | 只允许 `<packet_id>.json` / `annotation_draft.json`；文件名不得携带 code/name/T/group |
| sealing log / manifest / 错误信息 | production 域对 annotator 不可读；C4-D 的 fail 信息只引用 hash 与 gate 名 |
| packet 计数 | annotator 域任何时刻只存在当前 open REVEAL 的一个 packet；SEAL 后该 packet 文件保留只读，下一 packet 到达前不得出现第二个 packet 文件 |
| public anchor / report | 仅 commitment hash 与 boolean（§8） |
| draft 内容 | draft 不得包含 annotator 不该知道的信息的引用（机器可查部分：draft schema closed-world + evidence_note 仅允许引用本 packet 内字段路径） |

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

## 3. Annotation lifecycle（四态状态机，冻结）

```text
NO_ANNOTATION ──handoff──▶ DRAFT_EXISTS ──make_receipt──▶ READY_TO_SEAL ──seal txn──▶ SEALED
（无 annotator 域文件）     （draft 可自由改写）           （receipt 已 O_EXCL、        （C2 SEAL durable
                                                            不可变；draft 转只读）        + semantic replay PASS）
```

**状态由 persisted 文件集合派生，不存在独立可写的 state 字段**：

| 状态 | 派生判据（机器） |
| --- | --- |
| NO_ANNOTATION | annotator 域不存在 packet 文件 |
| DRAFT_EXISTS | packet 文件存在且有效；draft 文件可能存在 |
| READY_TO_SEAL | receipt 文件存在且 closed-world 有效且与 draft/REVEAL 事件三方一致 |
| SEALED | production chain 上存在绑定该 receipt 的合法 SEAL（§6 semantic replay） |

**各状态可变性（冻结）：**

- NO_ANNOTATION：无 annotator 对象；唯一合法写 = handoff；
- DRAFT_EXISTS：draft 自由改写（annotator 工作期）；schema 只在
  make_receipt 时 fail-closed 校验（工作期不逐笔拦截，准入在冻结点）；
- READY_TO_SEAL：receipt 自 O_EXCL 创建起**不可变**（重建/改写 =
  G-C4D-RECEIPT FAIL）；draft 转 0400 只读，其 SHA256 已记入 receipt
  （`draft_sha256`），任何 draft 变更 ⇒ 与 receipt 不一致 ⇒
  G-C4D-SEAL-PREFLIGHT FAIL（只能作废 receipt：作废 = 显式删除并留下
  selector-only 审计记录，然后回 DRAFT_EXISTS 重新起草——**作废的
  receipt 永不得进入 SEAL**）；
- SEALED：一切只读。

**Exact-bytes 原则（对应 C4-C 的 no-equivalent-regeneration）：**

> SEAL 事务消费的是 **exact persisted receipt bytes**
> （`receipt_sha256 = SHA256(exact canonical persisted receipt bytes)`）。
> 进入 seal transaction 之后任何一步都不得现场重新 canonicalize 一个
> "语义相同" 的对象再拿去封存——语义等价的重建物没有资格成为被 SEAL
> 的对象（C4-C 06f/06j 同型禁止）。

---

## 4. Annotation 载体 schema + 字节身份

### 4.1 Draft schema（c4d-draft-v1，closed-world）

```yaml
draft_version: c4d-draft-v1
session_id: c4-prod-0002
packet_id: <被揭示 packet 的 packet_id>
packet_sha256: <被揭示 packet 的 SHA256>
annotator_id: <opaque annotator 标识，冻结于 annotator session 建立>
annotation:                      # 标注学语义继承 CSR-7，不在此重定义
  rt_judgments:                  # 1..N 条，每条：
    - hypothesis_id: <CSR-7 冻结的 rt hypothesis id>
      verdict: SUPPORTED | SUPPORTED_PARTIAL | NOT_SUPPORTED | NOT_ASSESSABLE
      evidence_note: <=500 chars   # 仅允许引用本 packet 内字段路径
  overall_note: <=2000 chars
  flags: []                      # 闭集枚举，如 DATA_QUALITY_ISSUE；可为空
created_at: <canonical UTC>
updated_at: <canonical UTC>
```

- draft 文件 0600；`annotation.rt_judgments` 的 verdict 与 flags 为闭集
  枚举；字段集合 closed-world（多字段/缺字段 = G-C4D-DRAFT FAIL）；
- draft 序列化在 DRAFT 阶段**不要求** canonical（annotator 工具自由），
  但 `make_receipt` 会从 exact draft bytes 解析并校验。

### 4.2 Receipt schema（c4d-receipt-v1，closed-world，一次性冻结）

```yaml
receipt_version: c4d-receipt-v1
session_id: c4-prod-0002
packet_id: <同 draft>
packet_sha256: <同 draft>
reveal_event_hash: b5ec0ba1…437d5        # 绑定产生本 annotation 义务的那条 REVEAL
draft_sha256: <make_receipt 时刻 exact draft bytes 的 SHA256>
annotation: <draft 的 annotation 子对象，原样嵌入>
annotator_id: <同 draft>
receipt_id: <opaque unique id，创建时固定>
created_at: <canonical UTC，创建时固定>
```

- `make_receipt` 是唯一冻结点：读取 **exact persisted draft bytes** →
  closed-world 校验（draft schema + packet 绑定 + session 绑定 +
  reveal_event_hash == production chain 最后一条 REVEAL 的 event_hash）→
  组装 receipt → canonical 序列化 → **O_EXCL 写入**（0600，fsync
  file+parent）；
- `receipt_sha256 = SHA256(exact canonical persisted receipt bytes)`——
  SEAL 与 public anchor 绑定的都是这个 exact hash，不是逻辑字段；
- receipt 创建后：draft chmod 0400；receipt 不可变；重新创建同名
  receipt = O_EXCL violation（G-C4D-RECEIPT FAIL）。

### 4.3 三层字节身份

```text
draft_sha256    = SHA256(exact draft bytes at freeze time)   # 记入 receipt
receipt_sha256  = SHA256(exact receipt bytes)                 # SEAL 绑定
archived bytes  = C2 bytes/seal_annotation/<seq>.bin          # = exact receipt bytes
                                                              # （C2 append 预写
                                                              #  exact-byte gate +
                                                              #  verify 重证）
```

---

## 5. SEAL transaction（crash-safe，镜像 C4-C 结构）

### 5.1 与 C4-C publication 的差异（冻结理由）

C4-C 的 sealing 目录是**新建**对象，故用整目录 staging + renameat2
NOREPLACE 发布。C4-D 的 SEAL 是**向已发布 production log 追加**事件，
sealing 目录已在位，整目录替换会触碰已 durable 的 REVEAL 事实——禁止。
因此 SEAL 采用：**冻结 C2 API 的 in-place append + 事务级 fsync closure +
链导出 recovery**（C2 的 append 本身已内建 pre-write verify + gate +
exact-byte 预检 + 确定性 `bytes/seal_annotation/<seq>.bin` 路径）。

### 5.2 冻结执行顺序（SEAL transaction）

```text
(1)  production verify()（check_head=True）PASS；chain == [REVEAL r1]
(2)  语义前置（§6 证明子集）：receipt 有效、绑定 r1、状态 READY_TO_SEAL、
     draft 与 receipt 一致、SEAL 数 == 0
(3)  SEAL payload 构造（仅此三字段 + C2 自动 bytes_ref）：
       {opaque_case_id, T, receipt_sha256}      # 均取自 r1 payload / receipt
     content_bytes = exact persisted receipt bytes
(4)  C2 append SEAL（pre-write exact-byte gate：SHA256(receipt bytes) ==
     receipt_sha256；写入 bytes/seal_annotation/<seq>.bin；追加事件行；
     重写 head）
(5)  事务级 fsync closure：bytes 文件、log、head、sealing 目录逐一 fsync
(6)  production verify()（check_head=True）重新全链重放 PASS
(7)  C4-D semantic replay（§6）PASS
(8)  final invariant（§6.3）PASS
(9)  public anchor 原子更新（publish_anchor_durable 语义，§8）
(10) HARD STOP（第二 packet 权限另起，§7）
```

### 5.3 Recovery matrix（链导出，不依赖"文件存在即成功"）

恢复时从 genesis 全链重放（`verify(check_head=False)` + read_events），
按链事实分类：

| 链上事实 | bytes 归档 | head | 状态 | 恢复动作 |
| --- | --- | --- | --- | --- |
| chain=[REVEAL] | seal_annotation/N.bin 存在但无事件引用（孤儿） | 一致 | SEAL_PENDING_ORPHAN | 孤儿 bytes 无链意义；受控 retry（append 重写同 seq 路径） |
| chain=[REVEAL, SEAL]（从 genesis 可验） | 完整 | 陈旧（count/hash 落后） | SEALED_PENDING_HEAD | `sync_head(events)` 后 verify(check_head=True) PASS → SEALED（head 是 cache；链才是事实——与 C2 冻结语义一致） |
| chain=[REVEAL, SEAL]（可验） | 完整 | 一致 | SEALED | 只读；semantic replay 复证 |
| 其他（链验失败/SEAL 绑定错 receipt/FOREIGN） | — | — | SEAL_FORENSIC | HALT，禁止 retry |
| receipt 在、SEAL 无、无孤儿 | — | — | READY_TO_SEAL 保持 | 可重新发起 SEAL transaction |

与 C4-C 相同的纪律：恢复只消费 persisted state，绝不重新 canonicalize、
绝不重建 authorization/receipt identity。

---

## 6. 语义层：persisted semantic replay + final invariant

### 6.1 G-C4D-SEAL-REPLAY（每次事务后与恢复时强制）

在 C2 链重放之上，机器证明以下**三方一致**（全部从盘上对象派生）：

```text
receipt(persisted).receipt_sha256
  == SEAL event.payload.receipt_sha256
  == SHA256(archived bytes/seal_annotation/<seq>.bin)

receipt.reveal_event_hash == r1.event_hash
receipt.packet_id/sha256  == r1.payload.packet_id/packet_sha256
receipt.draft_sha256      == SHA256(exact current draft bytes)   # draft 未再变
SEAL.payload.opaque_case_id/T == r1.payload.opaque_case_id/T     # C2 已证闭包
annotator 域文件集合 == closed-world 期望集合                      # §2.3
```

任何一方不一致 ⇒ G-C4D-SEAL-REPLAY FAIL（fail-closed，HALT）。

### 6.2 SEALED 的机器定义（第二 packet 的前置，见 §7）

```text
first packet SEALED :=
    production chain 上存在 REVEAL r1（绑定 session c4-prod-0002）
  ∧ 存在 exact persisted receipt artifact（§4.2 有效）
  ∧ 存在合法 SEAL s1（C2 全链重放 PASS：闭包、无重复、exact-byte）
  ∧ persisted semantic replay（§6.1）证明 r1→s1 配对
```

### 6.3 Final invariant（SEAL 后）

```text
PRODUCTION_EVENT_COUNT == 2 且事件序 == [REVEAL_PACKET, SEAL_ANNOTATION]
sealed_count == 1；open_reveals == ∅
annotator 域 closed-world 成立；draft 只读
911d8b84…5dc81 仍为 CONSUMED（C4-C 事实不变）
```

---

## 7. 第二 packet reveal prerequisite + ordinal 授权链

### 7.1 强前置条件（冻结）

```text
first packet SEALED（§6.2 机器定义成立）
  ⇒ 才允许为 ordinal-2 candidate 生成新的 pre-authorization proposal
```

C2 的 strict alternation（SEAL 未写 ⇒ REVEAL(T_{i+1}) 禁止）是链层底线；
C4-D 在授权层再加一道：ordinal-2 proposal 的创建 API 在前置不满足时即
G-C4D-AUTHZ FAIL（不等到链上才被拒）。

### 7.2 ordinal/session-bound 授权 schema（c4d-reveal-v1，全新）

```yaml
authorization_version: c4d-reveal-v1          # 新版本号，不复用 c4c-auth-v1
scope: NEXT_REVEAL_ONLY                       # 新 scope 字符串
reveal_ordinal: 2                             # 显式序数
session_id: c4-prod-0002
sealed_prefix_head: <SEAL s1 后的 production head hash>
c3_manifest_commitment: 883c9869…d0b
candidate_packet_id: <frozen ordering 的第 2 个 candidate>
candidate_packet_sha256: <同上 exact hash>
authorized: true
authorization_id: <opaque，proposal 时固定>
created_at: <canonical UTC，proposal 时固定>
```

- candidate(ordinal N) 由 C3 冻结排序（frozen candidate tuple → earliest
  T → HMAC 字典序 + ocid tie-break）确定性导出，不引入任何新自由度；
- `sealed_prefix_head` 把新授权**密码学绑定到已封存前缀**：SEAL 未
  durable ⇒ 该 hash 不存在 ⇒ ordinal-2 proposal 无法合法构造；
- 三段式流程与 C4-C 同构（proposal 域 → human 批准 exact hash →
  approval authority → exact-copy permit → transaction），全部沿用
  C4-C 已冻结的 materializer 语义（权限契约 + closed-world + canonical
  bytes + frozen candidate binding + O_EXCL）；
- **旧授权彻底无意义**：`911d8b84…5dc81` 属 `c4c-auth-v1 /
  FIRST_REVEAL_ONLY`，在新 schema 下是非法输入（版本/scope/序数/前缀绑
  定四重不匹配，G-C4D-AUTHZ FAIL——fixtures 证明）；新 hash 与旧 hash
  无任何字段复用。

### 7.3 每一 packet 一次人工授权

ordinal-2 及之后的每一次 REVEAL 都需要**新的** human exact-hash 批准
（`NEXT_REVEAL_ONLY` authorization），消耗语义与 C4-C 相同（chain-derived
consumption）。不存在"批量预授权"。

---

## 8. Public surface（commitments/booleans only）

SEAL 后 public anchor 扩展为（沿用 publish_anchor_durable 的原子语义）：

```json
{
  "production_head_hash": "<SEAL 后 head>",
  "seal_receipt_sha256": "<receipt_sha256（annotation 内容的 commitment）>",
  "sealed_count": 1,
  "experiment_started": true
}
```

不暴露：packet identity、code/name/T/group、annotation 内容、下一
packet identity、packet 总数。`seal_receipt_sha256` 是内容哈希
（commitment），不破坏 blindness。synthetic report 同样只含 gate 名/
boolean/计数。

---

## 9. Synthetic / negative design gates（v0.1 即冻结清单）

沿 C4-C 纪律：target-aware fixture——preparation 必须成功，只有命中**指定
gate** 的失败才算 PASS；每个 materialization 类 fixture 显式断言目标对象
缺席/不可变。

| # | fixture | 构造 | 目标 gate |
| --- | --- | --- | --- |
| D01 | identity leak | annotator 域被塞入 identity 片段文件 | G-C4D-VISIBILITY |
| D02 | packet count leak | annotator 域出现第二个 packet 文件 | G-C4D-VISIBILITY |
| D03 | outcome leak | annotator 域被塞入 outcome/xp 工件 | G-C4D-VISIBILITY |
| D04 | handoff sha mismatch | 拷贝 packet bytes ≠ REVEAL payload packet_sha256 | G-C4D-HANDOFF |
| D05 | duplicate handoff | packet 文件已存在再 handoff | G-C4D-HANDOFF（O_EXCL） |
| D06 | draft extra field | closed-world 外字段 | G-C4D-DRAFT |
| D07 | draft missing field | 缺必填字段 | G-C4D-DRAFT |
| D08 | verdict 枚举外值 | rt_judgments.verdict 非法值 | G-C4D-DRAFT |
| D09 | receipt wrong packet | 自洽 receipt 但 packet_id 错 | G-C4D-RECEIPT |
| D10 | receipt wrong session | session_id 错 | G-C4D-RECEIPT |
| D11 | receipt wrong reveal | reveal_event_hash ≠ 链上最后 REVEAL | G-C4D-RECEIPT |
| D12 | receipt noncanonical | 持久化 receipt bytes ≠ canon(json) 且 approval/SEAL 引用与其一致（自洽陷阱） | G-C4D-RECEIPT |
| D13 | receipt rewrite | 已有 receipt 再 O_EXCL/改写 | G-C4D-RECEIPT |
| D14 | draft mutated post-freeze | receipt 后 draft bytes ≠ draft_sha256 | G-C4D-SEAL-PREFLIGHT |
| D15 | SEAL hash mismatch | SEAL payload receipt_sha256 ≠ 归档 bytes SHA256 | C2 delegated（exact-byte） |
| D16 | SEAL without REVEAL | 空/外来链上先 SEAL | C2 delegated |
| D17 | double SEAL | 对同一 (ocid,T) 二次 SEAL | C2 delegated |
| D18 | second REVEAL before SEAL | r1 未 SEAL 即尝试 r2 | C2 alternation + G-C4D-BOUNDARY |
| D19 | reused authorization | 以 c4c-auth-v1/FIRST_REVEAL_ONLY 结构申请 ordinal-2 | G-C4D-AUTHZ |
| D20 | wrong sealed_prefix | ordinal-2 proposal 的 sealed_prefix_head 错/缺 | G-C4D-AUTHZ |
| D21 | malformed persisted chain | production log 篡改后 SEAL/恢复 | G-C4C-PROD-REPLAY delegated |
| D22 | semantic three-way break | receipt/归档 bytes/event hash 任一方单独篡改（其余自洽） | G-C4D-SEAL-REPLAY |
| D23–D25 | crash windows | 孤儿 bytes / line-without-head / 完整 durable 三态恢复矩阵（§5.3） | recovery assertions |
| D26 | SEALED 前第二 proposal | r1 未 SEAL 时构造 ordinal-2 proposal | G-C4D-AUTHZ（§7.1 前置） |

另保留 C4-C 全部既有 fixtures 作为回归（live-chain 断言在 C4-D 实现期升
级为：恰 1 REVEAL（+SEAL 后 2）+ anchor 一致 + 双域 fingerprint 不变）。

---

## 10. 权限边界（本设计阶段）

本文件不授权任何执行。设计冻结后仍需逐级放行：

```text
C4-D DESIGN FINAL FROZEN（用户）
  → C4-D synthetic implementation + synthetic audit（不碰 production /
    不碰真实 annotator 域）
  → C4-D SYNTHETIC FINAL FROZEN（用户）
  → 真实 annotator handoff（production 域零变更；仅创建 annotator 域）
  → 真实 annotation draft（人工/标注 session）
  → 真实 receipt（机器冻结点）
  → 人工确认 seal 该 exact receipt_sha256
  → SEAL transaction（一次）→ semantic replay → anchor → HARD STOP
```

在设计冻结前，以下均为禁止：创建 annotator 域、handoff、draft/receipt、
SEAL、第二 packet proposal/授权、任何 production 变更、C4-C executor 修
改。

---

## 11. 开放问题（需用户裁决后进入 v1.0）

1. **annotator_id 语义**：本 pilot 中 annotator 是独立人类 session 还是
   标注代理？`annotator_id` 的分配与冻结方式（一次性 vs per-session）。
2. **rt_judgments 的 hypothesis 闭集**：CSR-7 的 rt hypothesis id 清单是
   否直接沿用 CSR-2/CSR-7 既有冻结集，还是为 pilot 定义最小子集（建议：
   显式列出将参与 pilot 的 hypothesis_id 清单并冻结于此）。
3. **receipt 作废语义**：DRAFT→READY 后发现 draft 错误时，"作废并重新
   起草" 是否允许在真实流程中使用（synthetic 必须覆盖），作废审计记录
   的存放层级（selector-only vs public boolean）。
4. **SEAL 后 annotator 域的 packet 文件保留策略**：只读保留（默认，便于
   审计对照）还是 SEAL 即清除（更严的后续盲态，但削弱可审计性）。
5. **第二 packet 的人工授权文案**：NEXT_REVEAL_ONLY 批准时用户看到的
   信息集合（建议与 C4-C 相同：仅 proposal_sha256）。
