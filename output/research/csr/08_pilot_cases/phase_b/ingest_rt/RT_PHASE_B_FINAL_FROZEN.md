# RT PHASE-B FINAL FROZEN

- 冻结基线：5302707（用户机器复算全过：82,892/24,802 两层 record_id 公式 0 mismatch；
  case84⊂universe84 零缺失；sidecar 24,802 条 JSON 全解析、零空 payload、与 CSV 精确互指）
- 冻结链：DATA_PLAN FROZEN @ fab6f5c → INGESTION CONTRACT v1.0 FROZEN @ c22797f →
  RT RUNNER RELEASED @ bf9077d → RT FULL INGESTION PASS @ ac6e87f →
  GRAIN ERRATUM ACCEPTED @ 6cffa81 → RECORD-GRAIN-PAYLOAD FIX PASS @ 5302707
- 数字（终版）：raw 4,757,083 行；universe84=82,892；case84=24,802；
  股日复合键 24,510；合法多行 292（lhb 122+dzjy 170）；rejects=0；
  2824/2824 请求 COMPLETE
- 消费契约：Phase C blind packet 只消费 case84 record index +
  经 record_id 解析的 frozen payload（RT_RECORD_GRAIN.yaml phase_c_consumption；
  禁止 bare stock-day join）
- **证据边界硬约束（用户终审裁定）**：当前 LHB endpoint=龙虎榜**摘要**通道
  （上榜原因+净买/买/卖/成交额聚合结构），**无席位字段**——不得作为
  CSR-4 E-STK-05（龙虎榜席位）的席位级证据；E-STK-05 席位证据需另补
  席位级 endpoint/官方源（独立工作项，不阻塞 Phase C）
- RT ingestion 架构此后不再修改（除非发现真正的契约错误）
