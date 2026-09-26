# CSR-8 Phase C Blind Packet Generator — 设计草案 v0.1（待用户审计冻结后编码）

上游冻结链：CSR-7 协议 @ 8f4b1f2（case_sheet_schema / rt_blind_packet / annotation
blindness contract）→ RT Phase-B FINAL FROZEN @ 5302707（case84 record index +
payload sidecar）。本设计只做消费层，不改任何上游。

## 1. 输入契约（全部只读）

| 输入 | 来源 | 用法 |
|---|---|---|
| case84 record index | normalized_case84_2021-03-08_2026-09-17.csv | 唯一记录索引（record_id 主键） |
| frozen payload | payload_case84_*.jsonl | record_id→行级证据内容 |
| case windows | ingest_plan.json spans | 每案例冻结窗（w_start/w_end） |
| 冻结日历 | frozen_exchange_calendar.csv | next_trading_day / as-of-T 判定 |
| 价格面板 | data/adjustment_baostock（Phase A 已用） | rt 图表截断于 T（不越 T） |

禁止：bare stock-day join（RT_RECORD_GRAIN phase_c_consumption）；
禁止读取 universe84 之外的宽缓存层进入 packet。

## 2. as-of-T packet 构造（CSR-7 rt_blind_packet 机器化）

每案例×每决策日 T 生成 packet：
- 可见记录 = record 的 available_date ≤ T（hindsight_filter 的 packet 级执行点）
- 价格/成交图表截断于 T（不展示完整窗口曲线）
- packet 序列化 canonical JSON（键排序）→ sha256 → sealing log 追加

决策日 T 网格（预注册，待用户裁决）：每案例窗内每 20 个取 1（与 CSR-7 案例研究
粒度一致）+ 窗内若干锚点日（G2=T0、G3=anchor、G4=launch）——具体网格冻结于
packet_plan.json，生成后不再调。

## 3. 盲化规则（CSR-7 原文执行）

不可见：group、selector outcome/metrics、window_end、T 之后一切数据、
xp_* 字段、真实 stock_code/name（→opaque_case_id）。
存放：案例真实 group 与 selector metadata → selector_only_hidden_block，
rt 序列锁定（时间戳+内容哈希）后方可解封。
opaque_case_id = SHA256(real_code | T | packet_salt)，salt 由用户在冻结时
提供（或登记机器生成并立即 sha256 封存，解封前不回读）。

## 4. evidence-mapping 硬约束（用户终审裁定落入 generator）

```
evidence_map:
  lhb_endpoint:
    provides: [上榜进入事实, 上榜原因, 龙虎榜聚合买卖结构(净买/买/卖/成交额)]
    forbidden_as: E-STK-05(龙虎榜席位)  # summary 通道无席位字段
    note: E-STK-05 席位级证据需独立 endpoint（官方源），未补齐前
          generator 对 E-STK-05 相关标注字段输出 NOT_OBSERVABLE_BY_CURRENT_SOURCE
          而非用 summary 顶替
  margin_sse/szse:
    provides: [两融余额/买入/偿还结构(个股日频)]   → E-STK-08 证据（AGGREGATOR+CONSERVATIVE_T1）
  dzjy:
    provides: [大宗成交价/量/额/买卖营业部]        → E-MRG 大宗通道证据
```

## 5. 产物（对齐 CSR-8 四类可审计产物）

1. packet_manifest.json：每 (case,T) 的 packet sha256+记录数+端点分布；
2. sealing_log.jsonl（append-only）：时间戳+packet sha256+opaque_case_id；
3. packet 文件本体（按 opaque_case_id/T 归档，git 入轻量样本+全量 sha 清单）；
4. blind_packet_audit.md：盲化自检（leak scan：packet 内不得出现真实代码/
   group 词/窗末信息——机器扫描+命中即 FAIL）。

## 6. 与 XP 侧的边界

本 generator 仅产 rt packet。xp packet（ownership 披露到达）依赖 OQ-1 巨潮
join——在 OQ-1 冻结前 XP 层保持 BLOCKED_FOR_PIT（契约已定），Phase C rt/xp
两 session 分离规则不变（CSR-7 annotation blindness contract）。

## 7. 待用户裁决的开放点

- OP-1 决策日 T 网格（§2 建议值）；
- OP-2 opaque_case_id salt 的产生方式（用户提供 vs 机器生成封存）；
- OP-3 G5 案例（PROVISIONAL_PENDING_PIT_REVALIDATION）是否本轮先出 packet
  （rt 层不依赖行业表，可以先出；xp 层等 PIT 行业表）。
