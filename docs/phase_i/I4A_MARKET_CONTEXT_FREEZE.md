# CSR-8 Phase I / I4A — External Market Context Freeze（数据 / 溯源 / 预注册）

*Contract:* `i4a_preregistration.json` · **sha256 `b12783420d8e4d2428c0e895f1114a97143b28dcd46fe2d54d8c2ee6bb06b49a`**
*Mode:* I4A 只冻结数据与合同，**零关系结果**（无 R5、无 delta、无方向检验）。I4B 按《合同》执行 readout。
*顺序（按裁定，ERR-I3-1 教训）:* data inventory → PIT/provenance audit → coverage matrix → preregistration → freeze。

## 数据冻结（少而有经济意义的 context 原则）

| 项 | 冻结值 |
|---|---|
| 大盘指数 | **000985 中证全指**（单一指数，选型理由=全市场代理对应 ETF 跨行业配置通道；冻结时零 I4 结果存在，无"看结果选指数"空间） |
| 价格口径 | 原始收盘点位（指数无复权歧义） |
| 数据 | 1280 个交易日（2020-08-12 ~ 2026-04-30），双段腾讯 fqkline HTTP 采集，URL+规范化文件 sha256 入 `docs/phase_i/evidence/manifest.json`，重跑脚本可复现 |
| PIT 规则 | 指数 EOD 当日公开；分析只用 **trade_date < T**（双重余量） |
| Regime 定义 | 二元：close(T 前最后交易日) vs 其前 120 交易日收盘中位数 → UP/DOWN。唯一参数=120（跨两个季度披露周期），中位数法，无阈值可调 |
| **Sector regime** | **DEFERRED**——仓库唯一行业数据是 2026-09-21 单时点证监会快照（5555 行含空标签）；回溯用于 2021-2026 观察日=未来信息，PIT 时间口径不可满足；如实记录而非回填。I4B 禁止临时替换 |

## 覆盖矩阵（全量普查，非 probe 推断）

- 122 readout 案例全部有 ≥120 日指数历史（0 例不足）；regime 分布 **UP=94 / DOWN=28**（语料偏 UP——I4B 每张表必须携带此语料特征）
- 每个 cell×regime 层 ≥3 个不同观察日（预注册下限，全过）；**DOWN 层恰好压线 3 日** → I4B 中所有 DOWN 层输出必须带 LOW-COVERAGE 横幅
- 明细：`i4a_coverage_matrix.json`（只含日期与计数，无任何路径结果）

## I4B 政策（冻结）

1. **只有 ETF 4v8、8v9 进 confirmatory**；ND vs NO_PIT 保持 DESCRIPTIVE_ONLY，外部 context 不得恢复其升级资格（仅可出描述表）
2. R4 硬门全量继承（naive/date-dedup/leave-max-cluster-out + ≥5 日/侧）；**新增 context 绝不取消 observation-date 控制**
3. INSUFFICIENT_CONTEXT_COVERAGE：任一层 <3 不同观察日 → 标记不可测；**禁止合并 regime、调阈值救结果**
4. context 分类确定性规则（基于各层 date-dedup delta 符号）：三层同号=CONTEXT_ROBUST；恰一层翻号=CONDITIONAL；两层都反于 I3 方向=MARKET_COMPOSITION_DEPENDENT
5. ETF 4v8 携带 I3 备注 *DIRECTION ROBUST / MAGNITUDE FRAGILE*（理论层只可引用方向）；8v9 在通过 context 检验前禁用 "regime threshold" 语言
6. 单指数单定义，**禁止指标动物园**；改指数/口径/窗口/regime 规则=违约

## 携带的解释边界

禁止因果语言；ETF 层禁止 actor 归因；两融/指数均为环境 modifier，资金状态标签不可变。

**变更控制：** 本合同随 commit 冻结（sha256 `b12783420d8e4d2428c0e895f1114a97143b28dcd46fe2d54d8c2ee6bb06b49a`）；改动需 append-only erratum + 显式用户授权。I4B 待你裁定后执行。

---

**ERR-I4A-1（append-only）**：commit 664b35d 的 message 文本引用了冻结中间态合同 sha `d1432e9b…`（路径迁移 data/→docs/phase_i/evidence/ 之前）；**生效合同 sha 以本文件正文与本 commit 内合同文件内容为准 = `b12783420d8e4d2428c0e895f1114a97143b28dcd46fe2d54d8c2ee6bb06b49a`**。数据文件仅移动位置未改内容（manifest sha 复核一致）。
