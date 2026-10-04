# Capital Decision Program — CD-0 Contract Freeze

*Contract:* `cd0_contract_freeze.json` · **sha256 `8470820595b4ba5fdc2fc089edeab33a19f369447a1042eceef32631978087c6`** · 数据可得性审计 `cd0_data_availability_inventory.json`
*Status:* **CAPITAL DECISION PROGRAM ACTIVE · CD-0 FROZEN（任何新生产之前）· CSR-8: H IMMUTABLE / I FROZEN / J CLOSED / K NOT STARTED**

**CD-0 范围铁律**：本阶段不证明任何市场结论——只允许 schema inventory、覆盖普查框架、数据可得性审计、合同冻结。看过 G0–G5 结果后不得回来修 state 定义。

## 合同 1 · Decision Contract
最终只服务六类决策：市场风险预算 / 板块优先级 / 候选股过滤 / 个股排序 / 建仓区间 / 持仓加减退出。任何新特征必须映射到 ≥1 决策，否则不进生产链（研究 annex 允许，生产链封闭）。

## 合同 2 · PIT / Provenance Contract
一切历史特征满足 `available_at <= decision_time`；sector membership 必须版本化（仅允许 `sector_of(stock, T)`），当前标签回填历史永久禁止；**缺失 fail-closed**（INSUFFICIENT_DATA / NO_PIT_DATA），默认补值伪造状态禁止；数据集带来源+时间+哈希，原始证据可重建。

## 合同 3 · Support-First Contract（总合同级）
**Phase J 的教训上升为程序级强制约束**。适用于 L1 四态、L2 板块状态、lifecycle 八态、accumulation 标志、G0–G5 分层。任何离散状态进入决策或验证前必须先有冻结的 support census：raw count / distinct dates / time span / 最大同日簇倍数 / 板块与市场覆盖 / 长期空窗 / 时代集中。**支持不足 → 结论 INSUFFICIENT_SUPPORT**；调阈值、合并状态、换窗口抢救一律禁止。顺序：先普查，后使用。

## 合同 4 · Sector Contract
三级层级冻结（L1/L2/L3，第一版只做有投资意义的粒度）；membership schema 含 valid_from/valid_to/source/available_at；来源优先级在 CD-1 抓取前声明。**CD-1 第一个问题不是"哪个板块强"，而是"我们是否拥有足够细、足够历史化、又有足够 support 的分类"**——每级先做历史覆盖普查；越细越碎裂，每级的 support 必须先证明可研究。

## 合同 5 · Observable Cost Contract
"成本" = 基于成交、换手与公开持仓估算的 **observable cost structure**，永不声称"庄家真实成本"。四层成本（C0 长期 / C1 markup / C2 高位套牢 / C3 再吸筹）；schema 字段逐一标注直接观测 vs 模型推导；survival 双模型（exp(−k·turnover) 与 1−adjusted_turnover）**先冻结后看结果，禁调 k**；生产字段使用结构语言。

## 合同 6 · Lifecycle Contract
八态语义现在冻结：BASE_FORMING / ACCUMULATION_CONSISTENT / MATURE_ACCUMULATION / MARKUP / PULLBACK / RE_ACCUMULATION_CONSISTENT / DISTRIBUTION_RISK / STRUCTURE_BROKEN。**状态 = 资本/筹码结构解释，不是 actor intention**（_CONSISTENT 后缀 = "与吸筹一致"，不断言存在吸筹者）。阈值不在 CD-0 冻结——CD-5 冻结且每态先做 support census；看过结果后修语义禁止；转换规则化、机器可审计、每次转换输出证据向量。

## 合同 7 · Outcome / Decision-Value Contract
评价族**现在冻结**：R5/R10/R20 · MFE/MAE · 最大回撤 · breakout failure rate · markup conversion rate · second-wave success rate · time-to-target · structure-break probability。双轴报告（预测效果 / 交易价值）；最终判定永不只看平均收益，必须含风险调整与失败路径；CD-8 不得在看过结果后增删或重设权重。

## 合同 8 · Falsification Contract
G0 裸 breakout → G1 +market → G2 +sector → G3 +accumulation → G4 +supply absorption → G5 +cost support & lifecycle。**每级 marginal contribution 必须报告**（不只 G0 vs G5）——防"只有 Sector 有用却误以为整套理论成立"。若逐层加入不能稳定改善决策结果，**禁止新增变量挽救理论**。
**稳定性判据格式现在冻结**（CD-8 不得再选）：预注册回放窗口集上，层的 marginal contribution 方向一致比例 ≥2/3 且中位数方向为正；窗口集在 CD-8 预注册时声明。CD-8 的判决对象是漏斗的**实践价值**，不是统计显著性。

## 数据可得性审计（无市场结论）

| 资产 | 覆盖 | CD 可用性 |
|---|---|---|
| per_stock 价格（baostock） | 84 codes, 2021-01→2026-09 | ✅ 成本分布/outcome；**全市场扩展为缺口** |
| ETF 份额（SSE） | 13 codes, 2021-03→2026-09 | ✅ L1 特征；SZSE 缺失沿袭 |
| national_holdings_pit | 84 codes, 22 报告期 | ✅ 持仓层（仅 84 股） |
| market_index_000985 | 2020-08→2026-04 | ✅ L1 基线；四态需更宽指数族 |
| csrc_industry_snapshot | 单快照 2026-09-21 | ❌ 历史回填禁止；仅作 CD-1 版本化构建输入 |
| dzjy / lhb / margin（raw） | 未审计 | 候选 L1/L2 特征；用前必须普查 |
| **全市场日线行情** | **缺失** | 🔴 CD-2 漏斗的阻断缺口 |
| **行业指数族 L1/L2/L3** | **缺失** | 🔴 L2 相对强度的阻断缺口 |

**下一步**：CD-1 PIT Sector Infrastructure——第一个目标是回答"是否拥有可作为中间层的板块分类"（版本化 membership + 每级覆盖普查），在其 GO 之前不启动任何生产。
