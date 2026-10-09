# R2-10 Position & Portfolio Policy Study — 预注册规格（冻结于执行前）

按用户裁定 2026-10-09（全文已入记忆 mem_mv08j818）：不再找指标，用已验证的 WHERE/WHAT/HOLD/EXIT 比较不同分批仓位与组合限制，回答「分批仓位能否管理掉启动不可知」。

## 设计骨架（五层）
1. Market 总预算档：RISK_ON 0.8 / NEUTRAL 0.6 / DEFENSIVE 0.4 / RISK_OFF 0.2（首版数值，回测可修订档位但不得逐日调）
2. Sector 分配 + 集中度帽：细分 ≤20% / 大行业 ≤35%
3. 个股目标仓位 = Market×Sector×T3×Support/HL（四因子，无新黑盒）
4. Exposure Ladder（核心）：BUILD 首仓 25% → T3 至 50% → 盈利+结构持续逐档靠满（利润融资式，+5% 一档，不涨不机械加）；UNDERCUT_TEST 减半；HL_RAISE=持有许可非加仓；BROKEN 归零不观察
5. 组合约束 + 候选替换（优先序 BROKEN<RISK_HOLD<BUILD<T3<T3+HL<盈利结构持续；新候选须优于最弱持仓）

## 实验臂（P0–P3，固定同一候选流）
- P0 一次性满目标仓（对照）
- P1 三段：30%→60%→100%（T3、盈利两跳）
- P2 四段：20→40→60→80→100 细梯
- P3 regime-aware ladder（BEAR 各段×0.5，BULL×1.0）
- 固定因子：候选流=current_scan 历史重放（月末事件、冻结 tier 规则）；成本假设双边 0.15%；无未来数据（档位跳变只用当日收盘可观测状态）

## 评价指标
CAGR / total return、maxDD、MAR、hit rate、capital efficiency（收益/平均exposure）、avg exposure、tail loss（5%分位单事件损益）、BROKEN 后损失、sector concentration 实测。

## 停止线
单次全量执行；P0–P3 外不加臂；不得按结果回填档位数值后重跑（可另立 R2-10b 显式注明）。

## 交付物
对照表 + 推荐 ladder + 与六句哲学的一致性检查；若 P1/P2/P3 均不优于 P0 → 记录「分批无增益」负结果。
