# CSR-8 Phase C Blind Packet Generator — 设计 v1.0 FROZEN

- 版本：v1.0（v0.1 @ ec9e84b + 用户 PHASE-C-DESIGN-FIX1 裁决六项 A-F 全部并入）
- 冻结依据：用户预授权"六项落盘后 v1.0 冻结并开始编码，不再重议 OP-1/2/3"
- 上游：CSR-7 @ 8f4b1f2；RT Phase-B FINAL FROZEN @ 5302707；RT_RECORD_GRAIN.yaml
- 本设计只做消费层，不改任何上游；RT ingestion 架构不再修改

## 1. 输入契约（全部只读）

| 输入 | 来源 | 用法 |
|---|---|---|
| case84 record index | normalized_case84_*.csv | record_id 主键 |
| frozen payload | payload_case84_*.jsonl | record_id→行级证据（经 §2 投影后使用） |
| case windows | ingest_plan.json spans | w_start/w_end（进入 selector_only 层） |
| 冻结日历 | frozen_exchange_calendar.csv | T 网格与 next_trading_day |
| 价格面板 | 冻结 TDX 未复权面板（与日历同源 5240 文件） | §5 决策时钟/图表截断 |

禁止：bare stock-day join（RT_RECORD_GRAIN phase_c_consumption）；
禁止将 frozen sidecar **原样**送进 packet（必须先过 §2 投影）。

## 2. [FIX1-A] Endpoint payload allowlist（投影，非 blacklist）

投影在 generator 读 sidecar 后立即执行；leak gate 检查的是投影后 packet。
实查 payload 列（2026-09-26 全量 sidecar 抽样确认）与 allowlist：

margin_sse（9 列实际）：
- KEEP：信用交易日期, 融资余额, 融资买入额, 融资偿还额, 融券余量, 融券卖出量, 融券偿还量
- DROP：标的证券代码, 标的证券简称（identity）

margin_szse（8 列）：
- KEEP：融资买入额, 融资余额, 融券卖出量, 融券余量, 融券余额, 融资融券余额
- DROP：证券代码, 证券简称（identity）
- 注：margin_szse 无行内日期列（obs=meta query），投影保留值列即可

lhb（20 列——含未来信息，最严格）：
- KEEP：上榜日, 收盘价, 涨跌幅, 龙虎榜净买额, 龙虎榜买入额, 龙虎榜卖出额,
  龙虎榜成交额, 市场总成交额, 净买额占总成交比, 成交额占总成交比, 换手率,
  流通市值, 上榜原因
- DROP：序号（行号）; 代码, 名称（identity）; **上榜后1日, 上榜后2日, 上榜后5日,
  上榜后10日（直接未来收益——硬泄漏源）**; 解读（聚合商衍生文本，剔除出 RT 主证据，
  留 raw 层不消费）

dzjy（13 列）：
- KEEP：交易日期, 涨跌幅, 收盘价, 成交价, 折溢率, 成交量, 成交额,
  成交额/流通市值, 买方营业部, 卖方营业部（营业部=交易事实，非 identity）
- DROP：序号, 证券代码, 证券简称（identity）

规则化表述：**packet 只允许 allowlist 字段出现；任何不在 allowlist 的字段=投影即 FAIL**
（防 akshare 未来加列把新泄漏列带进 packet）。
evidence_map（同 v0.1 §4，维持）：lhb=进榜事实+上榜原因+聚合结构，禁 E-STK-05
席位级；遇 E-STK-05 标注输出 NOT_OBSERVABLE_BY_CURRENT_SOURCE。

## 3. [FIX1-B] salt / opaque_case_id / packet_id

```
secret_salt    = machine-generated 256-bit random        # 一次性生成
salt_commitment = SHA256(secret_salt)                     # 可入库（公开可验）
opaque_case_id = HMAC-SHA256(secret_salt, canonical_case_key)
                                                          # 同一案例跨 T 永远稳定
packet_id      = SHA256(opaque_case_id | T)               # 每个 T 单独身份
```

- canonical_case_key = 冻结案例键（Phase A sample_selection 的案例身份字段，
  如 case_id 或 code+group+T0 组合，编码前冻结）；
- secret_salt 存 selector-only secret storage（`data/csr8_phase_c/secret/`，
  .gitignore 排除、不进 packet、标注者不可访问）；**generator 必须可读以支持断点重放**
  ——不采用"生成后机器自己也不回读"方案（用户裁决：重放需求优先）；
- salt_commitment 入库（packet_manifest 记录），供事后证明 salt 未被更换；
- v0.1 的 SHA256(real_code|T|salt) 公式废弃（同一案例跨 T 会变 ID，
  与 CSR-7 案例身份和 progressive sealing 冲突——用户指出）。

## 4. [FIX1-C] 隐藏 packet plan（T 网格冻结）

```
base_T  = 每 case 自 window_start 起每 20 个冻结交易日取 1
anchor  = G2 T0 + G3 anchor + G4 launch（G1 仅基础网格；G5 暂不加行业 anchor）
T_list  = (base_T ∪ anchor) 去重后升序
```

- 规模（用户实算）：仅 20 日基础网格即 1,716 packet，均值 20.4/案例，最大 62——可接受；
- **packet_plan.json 整体=selector_only_hidden_block**：anchor_reason、完整 T 列表、
  总 packet 数、"未来还有几个 T"对标注者全部不可见；标注者在 sealed(T_i) 前只能看到
  当前 T 的 packet；
- packet_plan 生成时即定稿（含全部 T 的规划），文件落 selector-only 目录，
  其 SHA256 入库作完整性承诺（内容不进 git）。

## 5. [FIX1-D] Reveal/Seal hash-chain 状态机 + 决策时钟

事件流（append-only sealing log，每事件含 sequence_no/prev_event_hash/event_hash
构成 hash chain；event_hash=SHA256(sequence_no|prev_event_hash|event_type|payload)）：

```
for T_i in T_list（升序）:
    REVEAL_PACKET(T_i)      # packet 生成+揭示给标注 session；含 packet_id+packet sha256
    <标注 session 工作>
    SEAL_ANNOTATION(T_i)    # 标注回执封存（annotation 记录+提交时间戳）
    # 硬 Gate：SEAL_ANNOTATION(T_i) 未写入 ⇒ 禁止 REVEAL_PACKET(T_{i+1})
```

- 机器可证的 CSR-7 条款：sealed_at(T_i) < revealed_at(T_{i+1}) 由链上
  sequence_no 单调+prev_event_hash 链共同保证（时间戳为辅证）；
- 决策时钟=T 日收盘后：packet as-of 截断=available_date≤T；
- 价格图只显示 ≤T；价格口径=**冻结 TDX 未复权面板**（与日历同源，单一事实源；
  未复权不因未来公司行动回写历史——PIT-safe by construction，无需另证调整序列）。

## 6. [FIX1-E] 结构化 leak gates（升级字符串扫描为 schema 级）

投影后 packet 逐条过四 gate，任一命中即 packet FAIL（不生成）：
1. **schema gate**：packet 字段=白名单 schema；禁止 stock_code/name/group/
   window_end/selector_*/xp_*；
2. **evidence gate**：每条 evidence 的 available_date≤T；
3. **date gate**：packet 内任何日期字段值不得晚于 T；
4. **chart gate**：图表数据最大日期≤T。
（结构化判定替代裸字符串搜索——避免证券代码恰似金额数字的假阳性。）

## 7. [FIX1-F] G5 状态冻结

```
G1-G4 → PRODUCTION_RT                     （正常生成+正常标注）
G5    → PACKET_GENERATION_ALLOWED
        status = PROVISIONAL_BLOCKED_FOR_CASE_VALIDITY
        primary annotation 禁止；Phase-C 统计禁止
```

理由：G5 案例身份本身 PROVISIONAL_PENDING_PIT_REVALIDATION——若 PIT 行业表
重验后换样本，看过 RT 标注结果再改样本会破坏预注册边界。PIT 行业表重验并重新
冻结 G5 样本后，再开放这些 packet 进标注。XP 层维持 BLOCKED_FOR_PIT 直到
OQ-1 巨潮 join 冻结。

## 8. 产物（对齐 CSR-8 四类可审计产物）

1. packet_manifest.json：salt_commitment、packet_plan_sha256（承诺不泄内容）、
   每 (case,T) 的 packet_id+packet sha256+记录数+端点分布；
2. sealing_log.jsonl：hash chain（§5）；
3. packet 本体（按 opaque_case_id/T 归档；git 入轻量样本+全量 sha 清单）；
4. blind_packet_audit.md：leak gate 自检报告+投影统计（DROP 列计数）。

## 9. 与 XP 侧的边界

本 generator 仅产 rt packet；xp packet（ownership 披露到达）依赖 OQ-1 巨潮
join，冻结前 XP 层 BLOCKED_FOR_PIT；rt/xp 两 annotation session 分离不变
（CSR-7 annotation blindness contract）。

## 10. 实施件（下一步编码）

- `scripts/csr8_phase_c_packet.py`：命令=`salt`（一次性生成+commitment）/
  `plan`（隐藏 T 网格+sha 承诺）/`project`（allowlist 投影自检）/
  `reveal`（按状态机产 packet）/`seal`（写 SEAL_ANNOTATION）/`verify`
  （hash chain+四 gate 全量复验）；
- 全部检查独立跑+echo EXIT；规则 commit 与产物 commit 分离；
  packet/审计件 git add -f。
