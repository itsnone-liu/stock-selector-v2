# CSR-8 Phase B 数据方案（TDX-node 整合修订版）

- 修订日期：2026-09-26
- 依据：`tdx-node` 仓库（itsnone-liu/tdx-node @ 2026-09-26）——TDX_NODE_CAPABILITY_REPORT、
  CSR84_EVIDENCE_REPORT、archivist v1.2.0 smoke（COMPLETE / contract_met=true / 137/137）。
- 本文档取代 CHANNEL_PROBE.yaml 中 next 字段的单一 akshare 路线，成为 Phase B 的
  正式数据方案；CHANNEL_PROBE.yaml 降级为 akshare/东财路线的勘察记录。

## 1. 双节点架构

| 节点 | 位置 | 角色 | 不做 |
|---|---|---|---|
| **research-node** | Linux 主仓 stock-selector-v2 | 抽样/盲标注/sealing/分析层；akshare/东财历史通道；PIT 公告日链 | 不承担 Windows 侧采集 |
| **tdx-node** | Windows 本地（隔离客户端 tdx-tq-v773 + tqcenter 1.1.0 + 17709 HTTP） | 本地行情/股本/股东 content 数据面；forward-PIT 每日归档（计划任务 20:30） | 不做公告日链；GUI 只作控制面降级 |

分工边界（tdx-node 已声明，主仓接受）：TDX 变化日=生效日/完成日语义；
publication_date/available_date 一律由主仓侧公告索引补齐。

## 2. CSR-6 证据通道重排（source of record）

| 证据/数据 | SoR | 节点 | 状态（对齐 probe 状态阶梯） | PIT 路径 |
|---|---|---|---|---|
| 日线 OHLCV（84 案例） | baostock hfq/unadj（研究窗已冻结）+ TDX 日线交叉验证 | research / tdx | FROZEN（Phase A 已用）+ CROSSCHECK_PENDING | 交易日历天然 PIT |
| 除权事件 | TDX 分红送配（600519 十条级）+ baostock | tdx | CONTENT_VERIFIED（送转内部一致性 26/27 ≤2%） | 生效日语义；公告日由公告索引补 |
| 股本历史（**数据源语义：VERIFIED_ON_CSR84**；E-MKT-04/E-SEC-04=DATA_SOURCE_CANDIDATE_VERIFIED，CSR-6 状态暂不变） | TDX get_gb_info_by_date（股票侧） | tdx | VERIFIED_ON_CSR84（84 案例内语义可信；全冻结 universe 5,240 股 coverage 未证明） | 84 案例级 market_cap(T)=price(T)×share(T) 生效日语义成立。112 个 ≥1% 变化=送转内部一致性 26/27≤2%+公告抽查 2/2 命中（非 112/112 全量）。E-MKT-04 重评级前置=5,240 股全覆盖；E-SEC-04 另需 PIT 行业表+权重口径（自由流通 vs 总市值）预注册。满足后再提请，不在 Phase B 擅动 |
| 十大股东/十大流通（**E-STK-02** content 源；E-STK-01=股东户数由单独通道建设，TDX 不覆盖） | TDX download_file type=1（gd+ltgd 成对） | tdx | CONTENT_OK_PIT_PENDING（2035 快照/504 下载零错误/五组均衡） | TDX content × 公告索引 publication_date join（主仓侧） |
| 龙虎榜（历史） | akshare lhb_detail_em | research | CONTENT_OK_PIT_PENDING（probe 已确认 430 行/字段齐） | 聚合源无 timestamp 保守 T+1+availability_basis |
| 龙虎榜（forward） | TDX watchlist 每日归档（archivist LHB×20） | tdx | FORWARD_ARCHIVE_RUNNING | 归档起点 2026-09-26；只供未来事件，不回填历史 |
| 限售解禁（forward） | TDX unlock×20 每日归档 | tdx | FORWARD_ARCHIVE_RUNNING | 同上 |
| 个股两融明细（E-STK-08） | akshare margin_detail_sse/szse | research | 两所 endpoints 均已至少一次成功验证（SSE 1,906 行 / SZSE 1,981 行）；**当前运行健康状态以 CHANNEL_PROBE.yaml 为唯一事实源**（DATA_PLAN 不记录瞬时 health） | 交易所官方 T 日盘后；聚合源按 source timestamp 登记。**TDX GP03 系免费路线止损**（付费墙仅 TDX 侧，AKShare 通道不受影响） |
| 两融标的池历史 membership | akshare underlying 快照（每日存档从现在积累）+ TDX 分类 56/57（标签待确认） | research / tdx | SNAPSHOT_ACCUMULATING | 不能回溯——只能 forward 积累（两边口径并采，以交易所为准） |
| 增减持/户数/基金持仓（xp） | akshare（东财域） | research | 结构性判断见 probe 历史（各 endpoint 均曾成功验证或确认存在）；当前健康以 CHANNEL_PROBE.yaml 为唯一事实源 | 公告日链=巨潮 join（主仓侧统一做） |
| **ETF 历史份额** | 无（GP52 付费墙；get_gb_info=红线） | — | **INTERFACE_GAP_CONFIRMED**（TDX 侧二次确认 akshare 侧缺口） | 三选一路径已登记：升级权限复测 / 独立点时源 / PCF 每日归档不补历史（archivist 已在做 PCF×8） |
| ETF 列表/跟踪关系 | TDX 当前快照（1729/30 只） | tdx | SMOKE_OK_OPTIONAL_REFERENCE | 幸存者偏差——不回溯历史池 |
| PIT 行业时点表（G5 revalidation 依赖） | 官方历史分类快照+变更公告 | research | SOURCE_DESIGN_REQUIRED | 独立项；与 TDX 无关，不用现时表冒充 |

## 3. 红线（继承 tdx-node，主仓同等生效）

1. **ETF get_gb_info_by_date 永久禁用为历史份额**（当前快照铺满历史：三只 ETF 1250 日 unique=1）；
2. TDX GP52 / GP03 系免费路线止损（付费墙仅限 TDX 侧；两融历史由 research-node
   AKShare 通道承担，不受此红线约束）——不反复重试 TDX 免费路线；
3. 当前 ETF 列表/两融池不得倒灌历史 membership；
4. TDX 股本变化日是生效日不是公告日——任何"当时可知"判断不得引用。

## 4. 数据流契约（两节点统一字段）

- **瞬时 endpoint health 声明**：本方案只记录结构性事实（接口存在性/字段语义/覆盖
  范围/红线）；任何"当前 OK/当前 PENDING"以每次重跑的 CHANNEL_PROBE.yaml 为唯一
  事实源，其 next action 由 status 机器派生（probe result→status→next action），
  不在本文档手工维护；

- 主仓 ingestion 七字段：**observation_date** / source / source_record_date /
  publication_date / retrieved_at / available_date / availability_basis。
  CSR-6 核心时间链 observation_date→publication_date→available_date 适用于全部通道
  （XP 通道 observation≠trade：股东=报告期末、基金=季末、解禁=实施日）；通道自身的
  trade_date / report_period / event_date / effective_date 留在 payload，不进主键层；
- tdx-node 归档四件套（已实现）：retrieved_at / request / sha256 / outcome
  （SUCCESS_NONEMPTY ≠ SUCCESS_EMPTY ≠ FAILED，三分类永不混同）；
- 消费规则：tdx-node archive/<date>/manifest.json 为主仓唯一进口；主仓引用归档文件
  必须带 sha256（与 archivist 复验值一致才可用）；
- 回传通道（open question，待定）：scp/rsync 定期打包 / git-lfs / 手动 zip——
  首版允许手动，但每次回传在主仓登记 archive_sha256 清单。

## 5. Forward-PIT 累积窗声明

archivist 起点为 2026-09-26。Phase C 标注若需 forward 证据（T 日后事件推进），
从归档窗内取；归档窗之前的历史一律走 research-node 历史通道（akshare），
两通道不互补拼缝（同一事件禁止一半来自归档一半来自历史接口）。

## 6. 对 CSR-6 重评级的影响（提请下轮 CSR-6 修订时执行，不在 Phase B 内擅动）

- 股本历史数据源：VERIFIED_ON_CSR84（数据源语义验证；非 E-MKT-04/E-SEC-04 重评级）——
  E-MKT-04 需 5,240 股股本历史全覆盖后再提请；E-SEC-04 另需 PIT 行业表+权重口径
  （自由流通 vs 总市值）预注册（CSR-6 已冻结该开放问题）；
- E-STK-02（十大流通/十大股东 content）：覆盖确认（84/84 全覆盖、每股≥15 快照），
  availability 维持 LAGGED_VERIFICATION；E-STK-01（股东户数）由单独通道建设，本方案不涉及；
- ETF 份额类：缺口二次确认——CSR-6 的 contract_items_for_ingestion 中
  ETF 份额项标记 BLOCKED_ON_PERMISSION_OR_ALTERNATE_SOURCE。

## 7. Phase B 剩余工作（重排后）

1. ingestion 七字段契约 yaml 冻结（研究侧）；
2. rt 三通道（margin/lhb/dzjy akshare 历史）84 案例窗口拉取；
3. XP 公告日链设计（巨潮公告索引 join——十大股东 2035 快照是第一批消费者）；
4. 东财域冷却重试（户数 detail/增减持）；
5. PIT 行业时点表立项（G5 revalidation 唯一合规来源）；
6. tdx-node 归档回传机制选型与首次回传登记。
