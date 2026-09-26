# CSR-8 Phase C4-C — First Production Reveal Transaction Design

- 状态：DESIGN DRAFT，待用户审计；本文件不授权、不实现、不创建任何
  production 对象
- 基线：
  - C1 FINAL FROZEN @ `9292d0d`
  - C2 FINAL FROZEN @ `9d19be7`
  - C3 FINAL FROZEN @ `04f54e1`（commitment
    `883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b`）
  - C4 DESIGN v1.0 FINAL FROZEN @ `6fa5380`
  - C4-A/B FINAL FROZEN @ `4482e54`
  - readiness session = `c4-prod-0002`
- 设计阶段必须保持的状态：

```text
PRODUCTION_EVENT_COUNT = 0
READY_FOR_FIRST_REVEAL = true
HARD_STOP_BEFORE_FIRST_REVEAL = true
authorization = none
experiment = NOT STARTED
```

本阶段唯一交付物是本设计文档。不实现 production append，不创建
authorization，不修改 `c4-prod-0002`，不产生任何 production event。

---

## 1. 设计范围与不可逆性

C4-C 是整个 CSR-8 实验的唯一不可逆事务：第一条 production
`REVEAL_PACKET` 一旦 durable，实验即开始。因此 C4-C 的全部设计都围绕
一个目标：

> 在任意时刻（包括任意崩溃点）系统都能机器证明：
> - production 状态是什么；
> - authorization 是否已消费；
> - 二者永远一致，不存在中间态。

三份冻结对象构成事务：

1. immutable `FIRST_REVEAL_ONLY` authorization（§2）；
2. production REVEAL event payload extension（§3）；
3. crash-safe publication transaction（§4）+ recovery matrix（§5）。

---

## 2. Immutable FIRST_REVEAL_ONLY Authorization

### 2.1 唯一机器 schema（closed-world）

```yaml
authorization_version: c4c-auth-v1
scope: FIRST_REVEAL_ONLY
authorization_id: <opaque unique id>
session_id: c4-prod-0002
c3_manifest_commitment: 883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b
candidate_packet_id: <exact frozen candidate>
candidate_packet_sha256: <exact frozen candidate hash>
authorized: true
created_at: <canonical UTC timestamp %Y-%m-%dT%H:%M:%SZ>
```

冻结约束：

- **exact closed-world schema**：顶层 key set 必须等于上述九字段集合；
  任何 extra/missing 字段 FAIL-CLOSED（与 C4-A/B FIX2 同构的 schema gate，
  独立于任何 hash 门）；
- `scope` 严格等于 `FIRST_REVEAL_ONLY`；
- selector-only 文件权限 `0600`，位于 production session 目录内；
- **创建后 immutable**：任何改写、重写、追加即 FAIL-CLOSED；
  authorization 没有 `consumed` 字段——consumption 只能从 production
  chain 派生（§2.3）；
- `created_at` 为 canonical round-trip UTC 时间戳
  （`strftime(strptime(v)) == v`）；
- authorization 的 `candidate_packet_id` / `candidate_packet_sha256` 必须
  与 C4-A frozen `first_candidate_record` exact 相等（§3 绑定链）。

### 2.2 授权语义

authorization 的含义严格为：

> 授权 `c4-prod-0002` session 下的**这一份** frozen packet 产生**恰好一条**
> production `REVEAL_PACKET`。

- 不授权第二条 reveal；
- 不授权 SEAL；
- 不授权 annotation session 创建；
- 不授权 outcome 生成；
- 不授权修改 C1/C2/C3/C4-A/B 任何冻结事实；
- authorization 的存在本身不消费授权；只有 §4 事务完整成功才消费。

### 2.3 Chain-derived consumption

```text
authorization(authorization_id) 已消费
⇔
production sealing log 中存在一条合法 REVEAL_PACKET event，
其 payload 绑定该 authorization_id（并完整通过 production replay verify）
```

推论：

- production 0 event ⇒ 一切 authorization 均未消费；
- 不存在可被篡改的 mutable consumption 标记；
- 重复执行 `reveal-first` 必须先重新派生 consumption：若已消费，
  FAIL-CLOSED（不得重试、不得二次 reveal）。

---

## 3. Production REVEAL event payload extension

### 3.1 Payload 绑定字段

除冻结 C2 `REVEAL_PACKET` 字段外，第一条 production REVEAL 的 payload
必须额外 hash-bind：

```yaml
session_id: c4-prod-0002
authorization_id: <exact authorization id>
c3_manifest_commitment: 883c9869...
candidate_packet_sha256: <exact frozen candidate hash>
```

C2 verifier 对额外 payload 字段兼容（C2 @ `9d19be7` 冻结语义），无需修改
C2；event_hash = H(seq|prev|type|payload) 会把授权身份锁进 production
chain，使 §2.3 的 consumption 派生成为链上事实。

### 3.2 Exact binding 链（四层）

```text
authorization (c4c-auth-v1)
        ↕ exact equality
C4-A first_candidate_record
  (candidate_packet_id, candidate_packet_sha256, session_id, C3 commitment)
        ↕ exact equality (closed-world schema gate + commitment)
C3 frozen packet bytes
  (SHA256(bytes) == manifest entry sha256 ∈ manifest with canonical
   hash == 883c9869...)
        ↕ payload hash binding
production REVEAL event
  (session_id, authorization_id, c3_manifest_commitment,
   candidate_packet_sha256 全部进入 event_hash preimage)
```

每条边都是 exact equality / exact hash，不得存在"重新生成等价物"的第二
路径：production reveal 的 bytes 必须来自 C3 selector-only 已验证的
canonical packet 文件，不得由输入重算。

---

## 4. Crash-safe transaction

### 4.1 冻结执行顺序

```text
(1)  reverify C4-A/B frozen session
       (c4-prod-0002 manifest closed-world + permissions + candidate record)
(2)  reverify all frozen authorities
       (C1 salt/plan, projection, Phase-B blobs, calendar, price,
        C3 provenance 04f54e1 + artifact equality + boolean boundary)
(3)  independently recompute first candidate
       (FIRST-CANDIDATE SELECTOR total order)
(4)  verify immutable authorization exact binding
       (§2.1 schema + §3.2 四层绑定)
(5)  prove authorization unused from production chain
       (production replay: 不存在绑定该 authorization_id 的 REVEAL)
(6)  prove production sealing target absent
(7)  create same-filesystem staging sealing domain
       data/csr8_phase_c/production/c4-prod-0002/sealing.staging/
(8)  frozen C2 append(REVEAL_PACKET)   # 真实 append()，非 batch writer
(9)  fresh-load staged replay + mandatory head
(10) assert exactly 1 REVEAL / 0 SEAL
(11) fsync(packet bytes file)
(12) fsync(staged log)
(13) fsync(staged head)
(14) fsync(staging directory)
(15) atomic no-replace rename staging → sealing
(16) fsync(production parent session directory)
(17) fresh-load production replay
(18) assert exact final invariant (§6)
(19) authorization now chain-derived consumed
(20) HARD STOP
```

### 4.2 Publication 硬约束

- production sealing target（`sealing/`）必须此前不存在（步骤 6）；
- staging 与 production 必须同一 filesystem（`st_dev` 相等）；
- rename 必须 no-replace 语义：目标存在即失败；平台不支持原子
  no-replace 时 FAIL-CLOSED，**不得退化为 copy/delete**；
- 步骤 (11)–(14) 的 fsync 缺一不可；rename 返回 ≠ durable，必须补
  production parent session directory fsync；
- 全程不允许 annotation session 创建、SEAL、outcome、第二 REVEAL。

---

## 5. Recovery matrix（冻结）

对每个崩溃点，权威状态、consumption、retry 许可与恢复动作如下。
权威 production 状态的唯一判据是 **production sealing domain 的落盘
replay 结果**；authorization 状态永远由它派生。

| 崩溃点 | authoritative production state | auth consumed? | retry? | 恢复动作 | FAIL-CLOSED 条件 |
|---|---|---|---|---|---|
| (a) before C2 append (步 1–7) | sealing 不存在 → 0 event | 否 | 允许 | 清除 staging（若已建），重新执行事务 | authorities/session/authorization 任一验证失败 |
| (b) during staged append (步 8 中途) | sealing 不存在 → 0 event；staging 内容不完整 | 否 | 允许 | 删除整个 staging domain，重新执行事务 | staging 损坏且无法删除；或 staging 与 production 不同 filesystem |
| (c) after staged append, before staged replay (步 8–9 间) | sealing 不存在 → 0 event；staging 有 1 event 未验证 | 否 | 允许 | 删除整个 staging domain，重新执行事务 | staging replay 无法 fresh-load |
| (d) after staged replay, before fsync (步 9–11 间) | sealing 不存在 → 0 event | 否 | 允许 | 删除 staging，重新执行 | staged replay/assert 失败（1 REVEAL/0 SEAL 不成立） |
| (e) after fsync, before rename (步 14–15 间) | sealing 不存在 → 0 event；staging 已 durable | 否 | 允许 | 删除 staging，重新执行（或审计后重新走事务） | fsync 任一失败 |
| (f) after rename, before parent fsync (步 15–16 间) | sealing 存在但目录项可能未 durable → 掉电后可能回退到 (e) 或前进到 (g)；重启发按落盘事实判定 | 由落盘 replay 派生 | 视落盘结果 | 重启后先 fresh-load production replay 判定状态 | rename 与 parent fsync 之间不允许人工假设状态；必须以 replay 为准 |
| (g) after parent fsync, before production replay (步 16–17 间) | sealing durable，1 event（尚未断言 invariant） | 是（链上已存在绑定 REVEAL） | 禁止 retry | 补跑 production replay + invariant assert，完成事务报告 | replay 失败或 invariant 不成立 ⇒ 事务进入不可解释状态，HALT 并人工审计 |
| (h) after production replay (步 17–20) | final invariant 成立 | 是 | 禁止 | 无（HARD STOP；输出 public boolean summary） | 任何再次 reveal/seal/annotation 尝试 |

矩阵必须满足的全局不变量：

1. **不存在** "authorization logically consumed 但 production event 不可
   证明"：consumption 的唯一定义就是链上存在合法 REVEAL（§2.3），该状态
   无法构造；
2. **不存在** "production event 已 durable 但 authorization 被允许再次
   使用"：步骤 (5) 在每次事务开始时从 production chain 派生 consumption，
   durable event ⇒ retry 入口 FAIL-CLOSED；
3. (f) 的不确定性只存在于 rename 与 parent fsync 之间，且恢复动作是
   "以落盘 replay 判定"，不允许任何基于内存或日志推测的状态宣称。

---

## 6. Final invariant

事务成功后的唯一合法 production 状态：

```text
production event count = 1
event[0].event_type = REVEAL_PACKET
event[0] payload binds exact authorization_id
event[0] payload binds session_id = c4-prod-0002
event[0] payload binds c3_manifest_commitment = 883c9869...
event[0] payload binds candidate_packet_sha256 = <frozen candidate hash>
open_reveal_count = 1
sealed_count = 0

annotation session = absent
real annotation    = absent
next reveal        = forbidden
outcome            = absent
G5                 = BLOCKED
XP                 = BLOCKED_FOR_PIT
```

public boolean summary 只允许：

```yaml
session_id: c4-prod-0002
c3_manifest_commitment: 883c9869...
PRODUCTION_EVENT_COUNT: 1
FIRST_REVEAL_COMMITTED: true
OPEN_REVEAL_COUNT: 1
SEALED_COUNT: 0
HARD_STOP_AFTER_FIRST_REVEAL: true
```

不得包含 packet identity、code/name、T、case/group、future schedule。

---

## 7. Synthetic / negative design gates

实现阶段的 fixtures 必须在 synthetic/staging 域执行，真实
`c4-prod-0002` 在 synthetic 审计通过前完全不触碰。每条 fixture 必须命中
目标 gate，不得依赖 collateral failure：

| # | fixture | 目标 gate |
|---|---|---|
| 1 | authorization missing | G-C4C-AUTHZ |
| 2 | authorization schema extra/missing field | G-C4C-AUTHZ（closed-world） |
| 3 | wrong session_id | G-C4C-AUTHZ |
| 4 | wrong c3_manifest_commitment | G-C4C-AUTHZ |
| 5 | wrong candidate_packet_id | G-C4C-AUTHZ |
| 6 | wrong candidate_packet_sha256 | G-C4C-AUTHZ |
| 7 | authorization_id reuse（chain 已存在绑定 REVEAL） | G-C4C-AUTHZ（chain-derived consumption） |
| 8 | candidate record tamper | G-C4-NEXT |
| 9 | packet bytes tamper | G-C4C-BYTES |
| 10 | existing production sealing target | G-C4C-PUBLISH |
| 11 | staging not same filesystem | G-C4C-PUBLISH |
| 12 | no-replace unavailable / target exists at rename | G-C4C-PUBLISH |
| 13 | staged log tamper | G-C4C-STAGED-REPLAY |
| 14 | staged head missing | G-C4C-STAGED-REPLAY |
| 15 | published log tamper | G-C4C-PROD-REPLAY |
| 16 | attempt second REVEAL after success | final invariant gate |
| 17 | attempt SEAL | final invariant gate（sealed_count 必须 0） |
| 18 | attempt annotation creation | C4 边界 gate（annotation absent） |
| 19 | attempt outcome generation | C4 边界 gate（outcome absent） |

对应 gate 命名（C4-C 固定 gate 集）：

```text
G-C4C-AUTHZ          immutable authorization closed-world + exact binding
                     + chain-derived unusedness
G-C4C-BYTES          frozen packet bytes exact hash（复用 C4-B 语义）
G-C4C-STAGED-REPLAY  staged fresh-load replay + mandatory head + 1/0 assert
G-C4C-PUBLISH        same-fs + no-replace rename + fsync 序列 + target absent
G-C4C-PROD-REPLAY    published fresh-load replay + final invariant
G-C4C-BOUNDARY       无 annotation / 无 outcome / 无第二 reveal / G5 / XP
```

---

## 8. 权限边界（本设计阶段）

```text
MUST NOT create real authorization
MUST NOT create production sealing domain
MUST NOT import/call production append from any executable path
MUST NOT mutate c4-prod-0002
MUST NOT create annotation session
MUST NOT reveal first packet
```

本文件只是设计。即使 C4-C 设计将来冻结，下一步也应先做
synthetic/staging implementation 并通过审计；真实 `c4-prod-0002` 保持
完全不触碰，直到最后单独出现一次明确的 `FIRST_REVEAL_ONLY` 授权。

---

## 9. 实现顺序（设计冻结后）

1. synthetic implementation：temp domain 全链路（含全部 §7 fixtures）；
2. 审计 synthetic 结果；
3. 用户单独签发真实 authorization（c4c-auth-v1 immutable 文件）；
4. 执行一次 §4 事务于 `c4-prod-0002`；
5. §6 invariant + public boolean summary；
6. HARD STOP。
