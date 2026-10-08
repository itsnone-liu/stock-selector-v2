# CSR-8 H-PRE — National / Strategic Capital Evidence Extension Taskbook v1.0

## 0. 任务定位

本任务位于：

```text
PRODUCTION_INFRA_FINAL_FROZEN
        ↓
Phase H 已启动并完成 ordinal-3
        ↓
【暂停 H】
        ↓
National / Strategic Capital Evidence Extension
        ↓
独立冻结
        ↓
恢复 Phase H，从 ordinal-4 继续
```

本任务的目标不是重建 Phase C，也不是修改已冻结基础设施，而是：

> 在不破坏既有 production chain、packet commitments、candidate order、receipt/seal contract 的前提下，为后续 Phase H annotation 增加一层 PIT-safe、可审计、不可后验污染的国家级/战略资金证据。

## 1. 当前冻结与生产基线

基础设施冻结：

```text
PRODUCTION_INFRA_FINAL_FROZEN
@ cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca
```

其 audited implementation HEAD：

```text
04c89e7c43fb24e731871608ff40adee83221f64
```

Phase H 当前已真实完成：

```text
R1 → S1 → R2 → S2 → R3 → S3
REVEAL = 3
SEAL   = 3
open_reveals = 0
candidate_prefix = 3
```

因此本任务从当前 sealed prefix 开始。

## 2. Phase H 暂停规则

本任务期间：

```text
Phase H = PAUSED
```

明确禁止：

```text
生成 ordinal-4 production authorization
append R4
生成 ordinal-4 annotation
生成 ordinal-4 receipt
append S4
推进 candidate prefix
执行 analysis activation
执行 outcome join
```

允许：

```text
读取 frozen public / selector-side research inputs
构建新的 national-capital source adapter
构建历史证据面板
构建 sidecar/context
做 synthetic / historical regression
做独立审计
```

## 3. 核心设计原则

### 3.1 不修改既有 C1/C3 packet

当前 packet 结构保持原样：

```text
packet_id
opaque_case_id
as_of
evidence
price_panel
```

禁止向 frozen packet 中直接新增：

```text
national_holdings
national_team
etf_context
```

因为：

```text
packet bytes changed
→ packet_sha256 changed
→ C3 commitments changed
→ C2 authorization / receipt / replay assumptions changed
```

这会重新打开已经冻结的基础设施。

### 3.2 不修改既有 ordinal 1–3

必须保证：

```text
R1/S1
R2/S2
R3/S3
```

所有已有 packet、annotation、receipt、SEAL、authorization、review verdict、anchor 零修改。

### 3.3 新能力从 ordinal-4 起生效

定义两个 evidence profile：

```text
ordinal 1–3
= BASE_V1

ordinal >= 4
= BASE_V1 + NATIONAL_CTX_V1
```

历史 sealed annotation 不重写。

## 4. 外部源原型

来源仓库：

```text
itsnone-liu/national-team-holdings-tracker
```

当前参考 commit：

```text
0f4bd6a7d00f4084b52621c2597016a847febb52
```

该仓库仅作为：

```text
source prototype
actor discovery
ETF tracking universe
collector prototype
current snapshot reference
```

不得直接把 `data.json` 作为 CSR production SoR。

## 5. 第一版接入范围

只接两类数据。

### 5.1 National / Strategic Capital Ownership

包括：

```text
中央汇金
证金公司
社保基金
养老金
外管局系
国家大基金
```

主要数据：

```text
个股季度持仓
ETF季度持仓
持股比例
持股数量
季度变化
披露时间
```

### 5.2 ETF Total Share Context

包括宽基 ETF：

```text
沪深300
上证50
上证180
中证500
中证1000
创业板
科创50
中证A500
及冻结追踪清单
```

记录：

```text
ETF 总份额
份额变化
available_date
```

## 6. 第一版明确不接入

本任务不接：

```text
腾讯 MainNetFlow
腾讯 cap_main_net
新浪 r0+r1
板块 Top10 大单聚合
自动 insights
PE/PB 判断
52周位置判断
```

禁止把：

```text
大单资金流
```

解释成：

```text
国家队交易
```

## 7. N0 — Pause Anchor

首先生成：

```text
docs/audit/evidence/
national_capital_extension_pause_anchor.json
```

绑定：

```text
production chain = [R1,S1,R2,S2,R3,S3]
REVEAL = 3
SEAL = 3
open_reveals = 0
candidate_prefix = 3
production_head
latest review ledger head
Phase H campaign id
current git HEAD
```

机器重新验证：

```text
C2 full replay PASS
semantic replay PASS
ordinal 1–3 history PASS
candidate prefix PASS
```

N0 完成后：

```text
NO R4
```

## 8. N1 — National Actor Registry

新增：

```text
config/csr/national_actor_registry_v1.json
```

每个 actor：

```text
actor_id
canonical_name
aliases
csr_actor_class
actor_group
valid_from
valid_to
evidence_policy
```

建议：

```text
A1-HUIJIN
A1-ZHENGJIN
A2-SSF
A2-PENSION
A1-SAFE
A1-BIGFUND
```

要求：

```text
alias matching deterministic
no fuzzy uncontrolled match
closed-world actor IDs
```

## 9. N2 — Data Feasibility / Coverage Audit

目标：

```text
84 frozen cases
×
2021-03 → 2026-09
```

先回答：

```text
历史十大股东/十大流通股东是否可取
publication_date 是否可取
report_period 是否完整
historical depth 多长
source revision risk 多大

ETF 历史总份额可追溯多久
官方源覆盖如何
沪/深覆盖差异如何
```

输出：

```text
output/research/csr/national_capital/
national_source_coverage.parquet
```

状态枚举：

```text
AVAILABLE_PIT
AVAILABLE_DELAYED
MISSING
AMBIGUOUS
SOURCE_UNVERIFIED
```

## 10. N3 — Historical Raw Ingestion

每次 raw fetch 必须落：

```text
raw bytes
retrieved_at
source URL / endpoint
request args
source version
sha256
```

建议目录：

```text
data/csr8_national_capital/raw/
  holdings/
  etf_holdings/
  etf_shares/
```

## 11. N4 — PIT / Availability Contract

所有披露型数据必须同时区分：

```text
observation_date
report_period
publication_date
available_date
retrieved_at
```

合法进入 T 时点 context 的唯一条件：

```text
available_date <= T
```

禁止：

```text
report_period <= T
```

直接作为可见条件。

例如：

```text
2026H1
report_period = 2026-06-30
publication_date = 2026-08-28
```

则：

```text
T = 2026-07-15
```

不得可见。

## 12. ETF available_date

ETF 总份额第一版采用保守规则：

```text
trade_date = T
available_date = next_trading_day(T)
```

即：

```text
CONSERVATIVE_T1
```

## 13. N5 — Normalized Tables

至少生成四个标准表。

### 13.1 national_actor_registry

```text
actor_id
canonical_name
aliases
actor_class
actor_group
valid_from
valid_to
```

### 13.2 national_holdings_history

grain：

```text
stock_code
report_period
holder_rank
holder_name_raw
actor_id
shares
holding_ratio
change_shares
publication_date
available_date
retrieved_at
source_doc_id
raw_sha256
table_complete
source_grade
```

### 13.3 national_etf_holdings

```text
etf_code
actor_id
report_period
shares
holding_ratio
publication_date
available_date
raw_sha256
```

### 13.4 etf_share_daily

```text
etf_code
trade_date
total_shares
available_date
source
raw_sha256
```

## 14. Absence Semantics

必须区分：

```text
NOT_DISCLOSED_IN_TOP10
UNKNOWN
```

只有当：

```text
完整 TOP10 表成功取得
AND
actor 未匹配
```

才能输出：

```text
NOT_DISCLOSED_IN_TOP10
```

若表缺失、不完整或来源失败，只能：

```text
UNKNOWN
```

禁止：

```text
没抓到 = 没持仓
```

## 15. Ownership State Derivation

对每个股票、每个 T：

```text
latest available disclosure
+
previous available disclosure
```

派生：

```text
ENTRY
INCREASE
STABLE
DECREASE
EXIT
NOT_DISCLOSED_IN_TOP10
UNKNOWN
```

所有状态必须可从 normalized tables 确定性重算。

## 16. ETF Actor Attribution Firewall

ETF 总份额变化只能解释为：

```text
ETF_TOTAL_SHARE_EXPANSION
ETF_TOTAL_SHARE_CONTRACTION
ETF_TOTAL_SHARE_STABLE
```

禁止解释为：

```text
中央汇金当日买入
证金当日卖出
国家队当日净流入
```

## 17. N6 — National Capital Context Sidecar

对 ordinal >= 4 生成：

```text
national_capital_context.json
```

与原 packet 分离。

建议结构：

```json
{
  "context_version": "csr8-national-capital-v1",
  "packet_id": "<existing packet id>",
  "as_of": {
    "T": "YYYY-MM-DD",
    "availability_rule": "available_date<=T"
  },
  "records": [],
  "source_manifest_sha256": "<64hex>",
  "context_sha256": "<64hex>"
}
```

records 可包含：

```text
capital_layer
evidence_type
actor_class
state
holding_ratio
report_period
publication_date
available_date
evidence_level
context_record_id
```

## 18. Sidecar 隐私边界

sidecar 禁止暴露：

```text
stock_code
stock_name
case_key
group
future T
future candidate
future disclosure
outcome
analysis_labeled
```

允许：

```text
opaque packet binding
actor class
PIT-safe capital state
PIT-safe ETF context
```

## 19. N7 — Context Support Map

由于现有 annotation schema 已冻结，`evidence_refs` 继续只引用原 packet。

新增：

```text
context_support_map.json
```

示例：

```json
{
  "ordinal": 4,
  "packet_sha256": "<sha>",
  "context_sha256": "<sha>",
  "judgments": {
    "rt_H01": ["ctx-a"],
    "rt_H02": ["ctx-b"],
    "rt_H03": [],
    "rt_H04": ["ctx-c"],
    "rt_H05": [],
    "rt_H06": []
  }
}
```

## 20. H01–H06 对应关系

```text
H01 Accumulation
ENTRY / INCREASE
→ delayed direct / ownership evidence

H02 Locking
长期高持仓 + 多期 STABLE
→ 长期筹码稳定证据

H03 Markup
国家队 ownership 仅作背景，不单独证明 Markup

H04 External Participation
ETF 总份额扩张
→ market-level participation proxy

H05 Distribution
DECREASE
→ delayed direct evidence

H06 Loss of Control
EXIT / sustained DECREASE + 其它证据
→ support
```

## 21. Reviewer Exact Binding

ordinal >= 4 的 ANNOTATION review packet 必须同时绑定：

```text
packet_sha256
national_context_sha256
context_support_map_sha256
draft_sha256
```

其：

```text
input_commitment_sha256
```

必须从上述 exact hashes 构造。

任一 context 字节变化：

```text
old reviewer APPROVE = INVALID
```

## 22. 原 Receipt / SEAL 保持不变

禁止修改：

```text
c4d-receipt-v1
SEAL payload schema
C2 chain format
annotation contract
```

新的 national context 通过：

```text
H reviewer ledger
+
exact review packet
+
context_support_map
```

绑定到最终 annotation。

## 23. N8 — Regression / Negative Gates

必须通过：

```text
G-NC-01 actor registry deterministic
G-NC-02 raw provenance exact
G-NC-03 publication_date present where required
G-NC-04 available_date<=T only
G-NC-05 future disclosure excluded
G-NC-06 incomplete TOP10 != absence
G-NC-07 actor alias mapping deterministic
G-NC-08 ETF share actor attribution forbidden
G-NC-09 context contains no stock identity
G-NC-10 context deterministic rebuild
G-NC-11 context exact hash stable
G-NC-12 reviewer binds packet+context+support-map+draft
G-NC-13 R1-R3 replay unchanged
G-NC-14 production head unchanged during integration
G-NC-15 candidate order unchanged
```

## 24. Production Invariance Proof

在整个 H-PRE 阶段：

```text
production head
```

必须保持与 N0 anchor 完全一致。

即：

```text
R1,S1,R2,S2,R3,S3
```

零变化。

若出现：

```text
R4
S4
candidate prefix > 3
```

则：

```text
H-PRE FAIL
```

## 25. Independent Final Audit

最终审计重新检查：

```text
N0 pause anchor
source coverage
raw provenance
PIT rules
normalized tables
absence semantics
actor mapping
ETF attribution firewall
sidecar blindness
context deterministic rebuild
review binding
R1-R3 replay
production invariance
candidate order invariance
```

## 26. Freeze Marker

最终生成：

```text
docs/audit/evidence/
national_capital_context_extension_frozen.json
```

至少绑定：

```text
status:
NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN

source_repo:
itsnone-liu/national-team-holdings-tracker

source_repo_commit:
0f4bd6a7d00f4084b52621c2597016a847febb52

base_infra_freeze:
cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca

pause_chain:
R1,S1,R2,S2,R3,S3

effective_from_ordinal:
4

past_ordinals_mutated:
false

production_head_unchanged:
true

candidate_order_unchanged:
true

actor_registry_sha256
source_manifest_sha256
normalized_holdings_sha256
national_etf_holdings_sha256
etf_share_daily_sha256
context_schema_sha256
coverage_report_sha256

gate_results:
ALL_PASS

final_verdict:
APPROVE
```

## 27. Resume Gate

只有 `NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN` 正式落标后，才允许恢复 Phase H。

恢复时重新验证：

```text
current chain = R1,S1,R2,S2,R3,S3
open_reveals = 0
candidate_prefix = 3

production head
== H-PRE pause head

national context extension
= FROZEN

effective_from_ordinal = 4
```

然后才允许：

```text
prepare ordinal-4 NEXT_REVEAL
```

## 28. Phase H 恢复后的 evidence profile

Ordinal 1–3：

```text
BASE_V1
```

Ordinal >= 4：

```text
BASE_V1 + NATIONAL_CTX_V1
```

Phase I 分析时必须保留 `evidence_profile`，避免把两种 evidence regime 当成完全同质样本。

## 29. Phase I Cohort Rule

未来 outcome join 后：

```text
所有 ordinal
```

可用于原始：

```text
H01–H06 × outcome
```

分析。

但涉及 national capital context 的分析只能使用：

```text
NATIONAL_CTX_V1 cohort
```

即 ordinal >= 4，除非以后另开 supplemental assessment。

## 30. 明确禁止

本阶段禁止：

```text
修改 R1–R3
重建旧 packet
重写旧 annotation
重写旧 receipt
重写旧 SEAL
修改 candidate order
修改 C1/C3 commitments
修改 frozen annotation schema
将大单资金流归因于国家队
用 report_period 代替 available_date
因 source 缺失假定“不持有”
在冻结前推进 ordinal-4
```

## 31. 推荐 Commit Sequence

```text
NC0 pause anchor
NC1 actor registry + source contract
NC2 feasibility / coverage audit
NC3 raw historical ingestion
NC4 PIT normalization
NC5 national capital context builder
NC6 H reviewer context binding
NC7 synthetic / historical regression
NC8 independent final audit
NC9 NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN
```

## 32. 最终完成定义

只有全部满足：

```text
Phase H remained paused
R1–R3 unchanged
production head unchanged
candidate prefix unchanged
historical national ownership panel built
ETF share context built
PIT contract PASS
absence semantics PASS
actor attribution firewall PASS
blinded sidecar PASS
reviewer exact binding PASS
all G-NC gates PASS
independent final audit APPROVE
freeze marker committed
```

才允许宣布：

```text
NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN
```

随后：

```text
Resume Phase H from ordinal-4
```

## 33. 总体流程

```text
现在
R1,S1,R2,S2,R3,S3
        ↓
PAUSE H
        ↓
N0 production anchor
        ↓
N1 actor registry
        ↓
N2 coverage audit
        ↓
N3 historical raw ingestion
        ↓
N4 PIT normalization
        ↓
N5 normalized capital tables
        ↓
N6 blinded national context
        ↓
N7 reviewer binding
        ↓
N8 regression + negative gates
        ↓
Independent Audit
        ↓
NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN
        ↓
Resume H
        ↓
ordinal-4
        ↓
R4 → annotation + national context → S4
        ↓
continue Phase H
```

## 34. 最终原则

本任务不是重新扩建冻结基础设施，而是一个：

```text
evidence-source extension
```

目的只是让 Phase H 从 ordinal-4 开始拥有：

```text
长期国家级 ownership
+
国家队 ETF ownership 背景
+
宽基 ETF 总份额市场背景
```

同时保持：

```text
旧 packet 不动
旧 production 不动
旧 sealed annotation 不动
candidate order 不动
outcome blindness 不动
```

接入完成并冻结后，再继续 Phase H。
