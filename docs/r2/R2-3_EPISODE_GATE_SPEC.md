# R2-3 Episode-Granularity FINAL FALSIFICATION GATE — 预注册规范（冻结于运行前）

地位：对「月度粒度掩盖真实资金过程」假说的最后一次结构性检验。结果无论正负均不再在 E1-E5 内换口径寻找吸筹签名。

## 冻结项
1. **Anchors**：现有 10,609 episodes（data/r2/markup_episodes.jsonl）原样继承，不重选、不重定义。
2. **PIT**：特征窗口 [-20, 0]（anchor 当日及之前）；anchor 后信息不入特征。
3. **Matched controls**：仅匹配背景——同 L2、anchor 月 ±2 月、pos250 五分位层、20 日流动性(量)五分位层、同 regime 类；**禁止**用 margin/龙虎榜/筹码/E1-E5 核心变量匹配。控制组自身 forward 120d < 100%（未翻倍）。每 anchor ≤3 个控制。
4. **分层报告**：ALL / BULL(risk-on) / BEAR(depressed+risk_off)，不得因某层不利而合并。
5. **动态轨迹特征（预注册 8 项，跑后不得扩族）**：
   - T1 margin_slope：rzye(i)/rzye(i-20)-1
   - T2 cost_width_slope：量价带宽(i-5)/带宽(i-20)-1
   - T3 overhang_decay：上方套牢量占比(i-20)−(i-5)（正=衰减）
   - T4 cost_recon：现价±5% 区间量占比 60d 窗口(i) − 同测度(i-20)
   - T5 sell_eff_impr：下跌日单位量跌幅 后10日 vs 前10日（正=下跌效率降低）
   - T6 buy_eff_impr：上涨日单位量涨幅 后10日 vs 前10日
   - T7 digestion：cum_rel_vol20（20日累计量/250日中位量）× price_hold(close20d 末/窗口均值-1，接近0=不破位)
   - T8 ret20：窗口涨幅（背景对照项）
6. **成功标准（用户裁定原文）**：事先定义的动态结构组，方向在多历史窗口保持 × bull 层保持 × matched 后仍存在 × sector 条件不消失 × 对 markup conversion 有实际 lift。若只有单变量 lift 1.05-1.15、窗口乱跳、牛熊切换即失、matched 后消失、或需组合搜索才能出现 → 判 NO-GO。
7. **后续**：PASS→交互/生命周期整合；FAIL→accumulation-signature 线 NO-GO，转 sector-led 决策架构（市场资金环境→板块→相对强度/生命周期→个股→成本/持仓管理）。
