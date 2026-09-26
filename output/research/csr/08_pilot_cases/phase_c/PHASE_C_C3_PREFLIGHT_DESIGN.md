# CSR-8 Phase C3 — Real Packet Integration & Preflight

- 状态：DESIGN DRAFT，待用户审计后编码
- 上游冻结：Packet Design v1.0 @ 9474de8；C1 FINAL FROZEN @ 9292d0d；
  C2 FINAL FROZEN @ 9d19be7
- 本阶段目标：把真实 C1 投影与 C2 sealing engine 接通，完成全量 preflight；
  **不向标注者展示，不写真实 REVEAL，不生成真实 annotation**。
- 不允许：修改 C1 secret/plan/commitment、修改 C2 state-machine semantics、
  读取 XP、开放 G5 primary annotation、产生 Phase-C outcome 统计。

## 1. C3 交付边界

C3 是 Real Packet Integration & Preflight，不是实验启动。

```
C1 projected records + frozen hidden plan
        ↓
case/T packet construction
        ↓
allowlist + temporal + date + chart leak gates
        ↓
packet/record schema congruence
        ↓
C2-compatible append/replay preflight (isolated state domain)
        ↓
preflight manifest/audit; NO real reveal
```

通过 C3 后才有资格设计第一个真实 `REVEAL_PACKET`；C3 本身不产生
`REVEAL_PACKET` 事件，也不产生 `SEAL_ANNOTATION` 事件。

## 2. 只读输入与状态隔离

### 2.1 输入

| 输入 | C3 用法 | 权威性 |
|---|---|---|
| C1 projected case records | 读取 secret-domain 的 `projected_case84.jsonl`；不得回读原始 payload 代替投影 | C1 projection output |
| case record index | record_id、raw provenance、observation/available date、endpoint | RT Phase-B frozen |
| C1 frozen packet plan | 只读；每个 case/T 的隐藏计划由 generator 消费 | plan commitment binding |
| C1 salt | 只读；仅 generator/selector secret-domain reader 可用 | salt commitment binding |
| frozen exchange calendar | T 合法性/as-of 检查 | RT frozen |
| frozen unadjusted TDX price panel | chart 数据，截断到 T | C3 price input |
| C1 artifacts | source/projected schema、DROP proof、行守恒和 commitment 对账 | public audit artifacts |

C3 启动前必须运行 C1 binding verification；salt 或 plan commitment 不通过
则 FAIL-CLOSED，不生成任何 packet。

### 2.2 输出状态隔离

C3 使用全新、独立的 `data/csr8_phase_c/c3_preflight/` secret-domain 和
`output/.../phase_c/c3_preflight/` audit-domain；不得复用或写入 C2 dry-run
目录，不得写入真实 sealing log/head。

C3 产物只能是 preflight packet 与审计结果。`REVEAL_PACKET`、
`SEAL_ANNOTATION`、annotation receipt 和真实 session 状态均禁止出现。

## 3. Case/T 归属与身份

- case identity 只来自 C1 冻结的 `canonical_case_key`；不得通过裸
  `(stock_code, observation_date)` join 重新归属；
- `opaque_case_id = HMAC-SHA256(secret_salt, canonical_case_key)`，跨 T 稳定；
- `packet_id = SHA256(opaque_case_id|T)`；
- 每个 packet 必须带 `case_key` 的 selector-only 内部映射，但公开/预标注
  packet 不得包含 case_key、真实 code/name、group 或 industry；
- packet 内 record 只通过 `record_id` 关联投影 evidence，LHB/DZJY 不得被
  `(endpoint, stock_code, observation_date)` 合并；
- C3 必须证明 packet 中的 record_id 集合来自 C1 projected records，且无
  orphan/duplicate record_id。

## 4. 真实 packet 结构（preflight 版）

每个 `(case,T)` 生成一个 canonical JSON packet。其公开/标注侧结构只允许：

```yaml
packet_id: <sha256 opaque_case_id|T>
opaque_case_id: <stable hmac id>
as_of:
  decision_clock: CLOSE_AFTER_T
  T: <current decision date>
evidence:
  - record_id: <frozen record identity>
    endpoint: <frozen endpoint enum>
    observation_date: <date <= T>
    available_date: <date <= T>
    payload: <endpoint allowlist projection only>
price_panel:
  dates: [<dates <= T>]
  values: <unadjusted TDX close series>
status_axis: <PRODUCTION_RT | PROVISIONAL_BLOCKED_FOR_CASE_VALIDITY>
source_group_axis: PACKET_GENERATION_ALLOWED
```

字段禁止：`stock_code`、`name`、`code`、`group`、`industry`、`window_end`、
`selector_*`、`xp_*`、`outcome`、`future_*`、`上榜后*`、原始 payload 未经
投影的任何字段。`case_key` 只存在 selector-only 构造映射，不进入 packet。

LHB evidence mapping 是硬约束：当前 LHB 只能声明进榜事实、上榜原因和
龙虎榜聚合结构；不得映射为 `E-STK-05` 席位证据，并在要求 E-STK-05 时
返回 `NOT_OBSERVABLE_BY_CURRENT_SOURCE`。DZJY 的买卖营业部字段是其交易
记录内容，不等同于 LHB 席位证据。

## 5. 四类 leak gate（C3 必须逐 packet 执行）

### G-C3-SCHEMA：closed-world packet schema

`observed_packet_keys == FROZEN_PACKET_KEYS`；evidence payload 的字段集合
逐 endpoint 恰等 C1 allowlist。任何缺列、额外列、未知 endpoint 或禁止字段
均 FAIL-CLOSED，不 warning、不降级继续。

### G-C3-EVIDENCE：as-of 可用性

对每条 record：

```
available_date <= T
observation_date <= T
record_id 属于 C1 projected case records
```

`available_date` 为 NULL、不可解析或 evidence 超过 T 均 FAIL；不以
`observation_date` 替代 `available_date`。

### G-C3-DATE：日期字段上界

packet 内所有可识别日期字段（包括 payload 内日期字段）必须 `<= T`；
未来收益字段已经被 C1 投影拒绝，但 C3 仍二次硬检，防止 generator/schema
漂移绕过投影。

### G-C3-CHART：价格图截断

价格面板最大日期必须 `<= T`，且价格来源必须是冻结 TDX 未复权面板；
不得读取会因未来公司行动回写历史的调整序列。空面板、日期不单调或数据源
身份不符均 FAIL-CLOSED。

## 6. Schema congruence（C3 新硬门）

C3 必须在 packet 进入 C2 append 前验证：

```
packet.opaque_case_id == event.opaque_case_id
packet.T              == event.T
packet.packet_id      == event.packet_id
receipt.opaque_case_id == open_reveal.opaque_case_id
receipt.T              == open_reveal.T
```

同时：

```
SHA256(canonical_packet_bytes) == event.packet_sha256
SHA256(canonical_receipt_bytes) == event.receipt_sha256
```

C2 已验证的是 bytes→hash；C3 补的是 bytes 内部字段→event metadata。
任一不等即 FAIL-CLOSED。C3 preflight 使用 C2 engine 的独立状态目录做
append/replay proof，但不把该 proof 变成真实 reveal。

## 7. G5 与 XP 边界

| 轴 | G1-G4 | G5 |
|---|---|---|
| packet generation | 允许 | 允许 |
| case validity | production | `PROVISIONAL_BLOCKED_FOR_CASE_VALIDITY` |
| primary annotation | C3 仍禁止 | 禁止 |
| Phase-C statistics | C3 仍禁止 | 禁止 |
| XP | `BLOCKED_FOR_PIT` | `BLOCKED_FOR_PIT` |

C3 可以为 G5 生成并验证 preflight packet，但不能将其视为正式研究样本，
不能写入 primary annotation 队列或 outcome 汇总。

## 8. Preflight 产物与可审计不变量

公开 audit-domain（不含 salt、hidden plan 明文、真实 case identity）：

- `c3_preflight_manifest.json`：源 commitment、packet schema hash、packet 数
  的聚合统计、端点分布、G5 eligibility 计数、每 packet hash（不含 T 列表
  或 case-level plan 明文）；
- `c3_projection_audit.json`：C1 projection artifact hash、allowlist hash、
  dropped-column proof；
- `c3_leak_audit.json`：四类 gate 的通过/失败计数、失败原因枚举、无失败断言；
- `c3_congruence_audit.json`：packet/event/receipt congruence 结果；
- `c3_replay_audit.json`：C2-compatible isolated append/replay 结果；
- `C3_PREFLIGHT_REPORT.md`：明确写 `NO_REAL_REVEAL`、`NO_REAL_ANNOTATION`、
  `G5_BLOCKED`、`XP_BLOCKED_FOR_PIT`。

selector-only：完整 packet_plan、case/T 明文映射、salt、真实 case 解映射、
preflight packet 本体（如需保留）只进入 secret-domain，不进入公开 Git。

机器必须证明：

1. 每个计划 `(case,T)` 恰有一个 packet，packet_id 可重算且唯一；
2. 每个 packet 的 record_id 全来自 C1 projection，292 条合法多行不折叠；
3. 四类 leak gate 全通过；
4. schema congruence 全通过；
5. C2 isolated append/replay 全通过；
6. G5 只进入 eligibility 轴，不进入 primary/statistical 轴；
7. C1 salt/plan/source commitment 未变化；
8. 两次相同输入运行 canonical packet bytes/hash 完全一致；
9. 过程中不存在 `REVEAL_PACKET`、`SEAL_ANNOTATION`、真实 annotation。

## 9. C3 明确禁止与后继边界

C3 禁止：真实标注者访问、真实 reveal、真实 receipt、outcome 汇总、XP
join、OQ-1 解冻、PIT 行业表替换 G5、修改 C1/C2 冻结 artifact。

C3 preflight PASS 后，另立 C4 或用户明确裁决，才允许第一个真实
`REVEAL_PACKET`。C3 失败只修 C3 integration/generator，不回改 9292d0d
或 9d19be7。

## 10. C3 实施顺序（待本设计审计通过后编码）

1. C1 binding + source artifact verification；
2. selector-only case/T map 与 packet plan 读取；
3. allowlist projection consumption（禁止原始 sidecar 旁路）；
4. packet construction + canonical serialization；
5. 四类 leak gate；
6. schema congruence fixture（packet/receipt/event）；
7. C2 isolated append/replay preflight；
8. determinism、G5/XP boundary、NO_REAL_REVEAL/ANNOTATION 审计；
9. 公开 audit artifacts 与 C3 report；
10. 独立命令和退出码复核后 commit。
