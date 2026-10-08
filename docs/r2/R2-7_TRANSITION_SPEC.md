# R2-7 Support→Markup Transition Gate — 预注册规范（冻结于运行前）
H-transition：资本成本支撑有效前提下，哪些可观测条件显著提高 BUILD/T-WAIT → MARKUP 转换概率并降低崩破概率。

## 冻结项
1. **Cohort**：月末 bar、非 BROKEN 的有效支撑事件（ABOVE/IN_SUPPORT/UNDERCUT_TEST；cost_band 算法=R2-6 冻结版原样）。
2. **递进漏斗（嵌套，全部 as-of T0）**：
   - T0 = valid support（基线）
   - T1 = T0 ∧ market improving：L1 part(T0) > 前20日 part 均值
   - T2 = T1 ∧ sector leading：L2 sector_eq 20日累计 > mkt_eq 20日累计
   - T3 = T2 ∧ stock RS：个股 20日收益 > 所属 L2 20日收益
   - T4 = T3 ∧ activation：close ≥ 10日收盘最高（local reclaim）∧ ret20 ∈ [-10%, +5%]（回撤/平静后重启，继承 R2-3 已证结构）
3. **Outcomes**（60 bar 前瞻）：
   - A markup conversion：fwd 60d 内 max(high)/close(T0) − 1 ≥ +30%
   - B support breakdown：fwd 60d 内 close < band_low×0.95 连续 ≥5 bar
4. **报告**：每级 n / A率 / B率 + marginal delta；分层 = 时代(21-23/24-26) × regime(BULL/BEAR) × sector support（leading vs not）。必报每级边际贡献。
5. **禁止**：新特征、调 cost band、窗口搜索、龙虎榜/融资硬门（仅既有结论作 context）。
6. **三选一结论**：PASS（稳定递增条件链）/ SUPPORT_ONLY（支撑有效但启动不可判）/ FAIL（支撑优势亦不能保持）。
