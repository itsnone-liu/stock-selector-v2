# CSR-8 Phase C4 — Production Reveal Activation Design v0.1

- 状态：DESIGN v1.0 FROZEN（C4-DESIGN-FIX1 四项已并入，待实现 C4-A/B）
- 冻结依据：79f3de8 草案 + 用户 C4-DESIGN-FIX1 裁决；不再重议 FIX1 四项
- 上游冻结：C1 FINAL FROZEN @ `9292d0d`；C2 FINAL FROZEN @ `9d19be7`；
  C3 DESIGN FINAL FROZEN @ `3308de9`；price-source erratum EFFECTIVE @ `d1eb677`；
  C3 FINAL FROZEN @ `04f54e1`（provenance anchor）
- C3 authority：packet manifest commitment
  `883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b`
- C4 性质：第一次 production `REVEAL_PACKET` 是实验真正开始的不可逆边界。
  C4-A/B 永远不得隐式执行 C4-C。

## 1. C4 拓扑与权限层级

```text
C3 FINAL FROZEN
        ↓
C4-A  Production Session Initialization       [可自动执行，无 event]
        ↓
C4-B  First-Reveal Readiness Verification     [可自动执行，无 event]
        ↓
HARD STOP
        ↓
explicit FIRST_REVEAL authorization           [单 event，一次性]
        ↓
C4-C  exactly one production REVEAL_PACKET   [不可逆]
        ↓
production persisted replay + head verify
        ↓
HARD STOP
```

命令/接口边界必须是显式的：

- `init` 只能建立 fresh production session domain；不得写 production log/head；
- `readiness` 只能验证并输出 readiness summary；不得写 production event；
- `authorize-first-reveal` 只能产生一次 `FIRST_REVEAL_ONLY` authorization；
- `reveal-first` 是唯一允许调用 production C2 `append(REVEAL_PACKET)` 的入口；
- 不存在默认 `reveal` 命令，不存在 `reveal → seal → reveal-next` 自动链。

## 2. C4-A Production Session Initialization

production domain：

```text
data/csr8_phase_c/production/<session_id>/
```

### 2.1 Freshness 与权限

初始化必须 FAIL-CLOSED 证明：

- `<session_id>` 合法且唯一；
- production session 目录此前不存在；
- 父目录权限与 session 目录为 selector-only（目录 `0700`，文件 `0600`）；
- 不复用 C3 preflight state/artifact domain；
- production log、head、authorization、annotation session 均不存在；
- C4-A 完成后 production event count 必须仍为 `0`。

### 2.2 C4-A authority gates

初始化必须重验，不接受 C3-A/B 的口头结果：

- C1 salt commitment 与 hidden plan commitment；
- C1 projected output frozen hash；
- C3 authority commit `04f54e1` 与 manifest commitment
  `883c9869...`；
- C3 packet schema hash；
- BaoStock unadjusted price source manifest/root/per-file authority；
- Phase-B CASE_CSV blob identity；
- frozen calendar blob identity、embedded calendar SHA、1386 trading days；
- G5 = blocked；XP = `BLOCKED_FOR_PIT`。

### 2.3 Session manifest

selector-only session manifest（不得进入 public/audit 面）至少包含：

```yaml
session_version: c4-v0.1
session_id: <opaque unique session id>
c1_plan_commitment: <hash>
c3_packet_manifest_commitment: 883c9869...
c3_packet_schema_sha256: <hash>
price_source_commitments:
  source_id: baostock_unadjusted_v1
  fetch_manifest_sha256: <hash>
  per_stock_root_sha256: <hash>
phase_b_input_commitments:
  case_index_blob: <hash>
  calendar_blob: <hash>
  calendar_embedded_sha256: <hash>
state: INITIALIZED_NO_REVEAL
created_at: <timestamp>
```

public/audit summary 只能暴露 commitment 与布尔状态；禁止：packet count、
future T list、case/group identity、next-N schedule、真实 code/name。

## 3. C4-B First-Reveal Readiness

C4-B 读取 selector-only frozen plan，确定唯一合法 next packet，但输出仍不得
暴露真实 identity 或未来计划：

```yaml
READY_FOR_FIRST_REVEAL: true
session_id: <session id>
c3_manifest_commitment: 883c9869...
candidate_packet_hash_commitment: <opaque hash/commitment>
```

### 3.0 FIRST-CANDIDATE SELECTOR（C4-DESIGN-FIX1-A）

C1 hidden plan 只是 (case,T) 集合，production 0-event 时存在多个合法候选；
C3 isolated replay ordering 不构成 production schedule。C4 只冻结第一次
reveal 的候选选择规则，不替后续阶段冻结完整顺序：

```text
eligible cases
= G1-G4 only
  ∩ PACKET_GENERATION_ALLOWED
  ∩ non-XP

每个 eligible case:
candidate = 该 case 的 earliest T（hidden plan 升序第一个 T）

first case = argmin over eligible cases of
    HMAC-SHA256(secret_salt, "C4-FIRST-v1|" + opaque_case_id)

first packet = (first case, 其 earliest T)
```

性质：

- 完全由 reveal 前已冻结信息（salt、hidden plan、group axis）决定；
- 与 annotation/outcome/C3 replay order 无关；
- 不泄露 group/T 列表；
- selector-only 记录 `first_candidate_commitment`；
- C4-B 必须重算并证明结果唯一且 commitment 一致；
- 该规则不定义第二个及以后的 production reveal 顺序。

### 3.1 不重新生成 packet

C4 不重新生成 production packet。它必须消费 C3 FINAL FROZEN selector-only
packet bytes，并证明：

```text
SHA256(packet_bytes) == secret C3 manifest 中该 packet 的 sha256
SHA256(canonical(C3 secret manifest)) == 883c9869...
```

C4 只复制/引用已经验证的 canonical packet bytes 到 production reveal 操作域；
不能由相同输入重新计算第二条 packet identity 路径。

### 3.2 C4-B readiness gates

- C3 manifest commitment 完整匹配；
- FIRST-CANDIDATE SELECTOR 重算结果唯一且与 `first_candidate_commitment`
  一致（G-C4-NEXT）；
- candidate packet 仍通过 G5/XP boundary；
- candidate packet bytes exact hash 匹配；
- 当前 production predecessor state 为 zero events；
- readiness 本身不写 production log/head/event；
- readiness 后状态必须仍为 `INITIALIZED_NO_REVEAL`。

## 4. First-Reveal authorization

authorization 是独立的一次性 **immutable permit**，不是 session-wide permission，
也不是 mutable `consumed` 状态（C4-DESIGN-FIX1-B/C）：

```yaml
scope: FIRST_REVEAL_ONLY
session_id: <exact session>
c3_manifest_commitment: 883c9869...
candidate_packet_id: <exact packet id>
candidate_packet_sha256: <exact packet hash>
authorization_id: <unique id>
authorized: true
created_at: <timestamp>
```

### 4.1 Authorization gates

- scope 必须严格为 `FIRST_REVEAL_ONLY`；
- session_id、C3 commitment、candidate packet_id/sha256 全部 exact 匹配；
- `authorized=true`；
- authorization 文件 immutable：创建后不得改写；selector-only 权限；
- **consumption 由 production chain 派生**：authorization 视为 consumed 当且仅当
  production log 中存在以该 `authorization_id` 绑定的合法 `REVEAL_PACKET` event；
- 不存在可变 `consumed` 权威字段；重复消费尝试、session/authority/candidate
  mismatch、部分写入或状态不明均 FAIL-CLOSED；
- 一次 authorization 只允许一个 event，不能授权第二个 reveal。

### 4.2 Crash-safe first reveal（C4-DESIGN-FIX1-C）

REVEAL event payload 必须额外绑定授权身份（C2 verifier 对额外 payload 字段
兼容，无需修改 C2；event hash 将授权身份锁进 production chain）：

```yaml
session_id
authorization_id
c3_manifest_commitment
candidate_packet_sha256
```

发布方式为 staging + atomic publication：

```text
authorization immutable + unused
        ↓
verify no production sealing domain exists
        ↓
同文件系统 temporary sealing domain
        ↓
frozen C2 append(REVEAL_PACKET)   # 真实 append()，含 payload 绑定
        ↓
fresh-load persisted verify
        ↓
assert exactly 1 REVEAL / 0 SEAL
        ↓
fsync
        ↓
atomic rename temp sealing domain → production sealing domain
        ↓
再次 fresh production replay
```

崩溃语义：

- crash before rename → production 仍 0 event，authorization 未消费，可安全重试；
- crash after rename → production event 已存在，authorization 逻辑上已消费，
  绝不能再次使用。

C4-A/B 与 authorization 的生成/存在不消费授权；只有显式 `reveal-first`
的 staging→verify→publish 链完成才消费。

## 5. C4-C exactly one production REVEAL_PACKET

`reveal-first` 的冻结执行顺序（C4-DESIGN-FIX1-C）：

```text
verify session + frozen authorities
        ↓
recompute frozen first candidate (FIRST-CANDIDATE SELECTOR)
        ↓
verify authorization binds exact candidate (packet_id/sha256)
        ↓
verify no production sealing domain exists
        ↓
stage in temporary sealing domain (same filesystem)
        ↓
frozen C2 append(REVEAL_PACKET)   # frozen append(), not batch writer
        ↓
event payload binds authorization_id / session / C3 / candidate
        ↓
fresh persisted replay (staged)
        ↓
assert 1 REVEAL / 0 SEAL
        ↓
atomic publish (rename) sealing domain → production
        ↓
fresh production replay
        ↓
authorization now logically consumed
        ↓
HARD STOP
```

`reveal-first` 禁止：创建 annotation session、写 SEAL、自动 reveal next、
生成 outcome、解冻 G5、解冻 XP、修改 C1/C2/C3 artifacts。

### 5.1 Final state invariant after first reveal

必须严格为：

```text
production event count = 1
event[0].event_type = REVEAL_PACKET
open_reveal_count = 1
sealed_count = 0
annotation = none
next reveal = forbidden
```

production log/head 是唯一实际 event state；第一条 event 写入后必须从落盘
重新 load/replay，不能依赖 append 返回值或内存状态。

## 6. C4 fixed gates

1. **G-C4-SESSION**：fresh production domain、唯一 session identity、权限正确；
2. **G-C4-AUTHORITY**：C1/C3/price/index/calendar 全部 frozen authority 重验
   （`04f54e1` 为 provenance anchor，不要求当前 HEAD 等于它）；
3. **G-C4-MANIFEST**：canonical C3 secret manifest hash 与 `883c9869...` 一致；
4. **G-C4-NEXT**：FIRST-CANDIDATE SELECTOR 重算唯一、commitment 一致；
   G5/XP 不可作为 candidate；
5. **G-C4-BYTES**：production packet bytes 与 C3 frozen packet exact hash 一致；
6. **G-C4-AUTHZ**：`FIRST_REVEAL_ONLY` authorization 存在、immutable、绑定
   exact session/C3/candidate 且未 consumed；
7. **G-C4-APPEND**：使用冻结 C2 production `append()`（staged domain），
   禁止 batch writer；event payload 绑定 authorization_id/session/C3/candidate；
8. **G-C4-REPLAY**：staged 与 published 两次 fresh-load persisted replay +
   mandatory head；最终恰为一个 open REVEAL、零 production SEAL。

### 6.1 C3 authority semantics（C4-DESIGN-FIX1-D）

`04f54e1` 是 frozen audit reference / provenance anchor，不是 HEAD 约束：

- 该 commit 必须存在于仓库历史；
- 当前消费的 C3 authoritative artifacts 与其冻结 authority 一致：
  - manifest commitment = `883c9869...`；
  - packet schema hash = frozen value；
  - C1/source commitments = frozen values；
  - secret C3 manifest canonical hash = `883c9869...`；
  - packet bytes hash = manifest entry。

## 7. Synthetic / negative gates（设计阶段，不触碰 production）

C4 设计审计和实现测试必须使用独立 synthetic domain 或 temporary copy；不得
调用 production append：

- existing production directory → G-C4-SESSION FAIL；
- C3 authority/manifest mismatch → G-C4-AUTHORITY/MANIFEST FAIL；
- modified secret manifest → G-C4-MANIFEST FAIL；
- zero/multiple recomputed first candidates → G-C4-NEXT FAIL；
- packet bytes one-byte mutation → G-C4-BYTES FAIL；
- missing/already-consumed/candidate-mismatched authorization → G-C4-AUTHZ FAIL；
  （consumed 判定 = production chain 中存在绑定该 authorization_id 的 REVEAL）
- batch-writer substitution → G-C4-APPEND FAIL；
- staged tamper / 缺 fsync / 非 atomic rename 路径 → G-C4-APPEND FAIL；
- persisted log tamper/truncation/missing head → G-C4-REPLAY FAIL；
- attempted second reveal or seal after first reveal → final-state gate FAIL。

每条 negative injection 必须命中目标 gate；不得通过更早的 collateral failure
伪造证明力。production domain 在设计/测试阶段保持不存在。

## 8. Public boundary and hard stops

C4-A/B public summary 只能包含：

```yaml
session_id: <opaque>
C3 authority commitment: 883c9869...
READY_FOR_FIRST_REVEAL: <boolean>
PRODUCTION_EVENT_COUNT: 0
HARD_STOP_BEFORE_FIRST_REVEAL: true
```

不得包含 packet count、T 列表、case/group identity、真实 code/name、future
schedule 或 candidate 的可逆 identity 映射。

只有用户/授权方明确批准并提供匹配的 `FIRST_REVEAL_ONLY` authorization，才可
进入 C4-C。C4-C 完成第一个 REVEAL 后立即停止；任何后续 SEAL/REVEAL 必须另立
后续阶段/权限，不由 C4 v0.1 自动执行。

## 9. Implementation boundary

设计冻结后先实现并测试 C4-A/B，默认路径只允许：

```text
init → readiness → HARD STOP
```

`reveal-first` 必须显式存在、显式授权、默认不可调用；在用户明确授权前，不得
创建 production session event，不得调用 production C2 append。 
