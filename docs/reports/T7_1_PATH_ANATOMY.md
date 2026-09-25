# T7.1 报告：Post-REDUCE Path Anatomy（描述性路径地图）

> **身份声明（contract segment_protocol.t7_1）**：全段描述性、无 candidate 选择。
> 本报告不含任何假设检验（无 diff bootstrap、无 p 值、无多重校正——G20 强制），
> 所有组间差异**只记录、不评估**；任何表观差异不得被引用为 separator/veto/确认
> 论据——那是 T7.2 DEV-only discovery 的工作。数字全部来自
> `output/research/t7/01_path_anatomy/t7_1_report_data.json`。

## 1. 产物

- `t7_1_trajectory_map.parquet`：1,176 行 = 3 segments × 3 groupings（by_type 4 组 /
  by_false_recovery 2 组 / by_true_recovery 2 组）× 7 变量 × 7 checkpoints
  （R+1/2/3/5/10/20/40）；每格 = 中位 level + **双 cluster 独立 level CI**
  （ci95 = stock_code 聚类 bootstrap；ci95_t0date = T0_date 聚类 bootstrap；各 B=2000，
  percentile 2.5/97.5；**level CI 而非组间 diff CI**）。R1 修正：初版仅实现
  stock_code 单 cluster 而报告宣称双 cluster——现按 contract 继承双 cluster units
  真正生成两套 CI（G21b 校验两套字段与标签）。
- 分组守恒（G8）：by_type 四组（RECOVERED_ADD 15,646 / NO_RECOVERY 11,858 /
  FAILED_EXIT 3,338 / CENSORED 418）互斥完备 partition 31,260 anchors；
  by_false_recovery 限于 RECOVERED_ADD；by_true_recovery 为 T7.0 新尺子（TR 9,463）。
- 变量：ret_vs_r0 / drawdown_from_peak_log / dist_ref20 / volume_load_vs_prebreak /
  turnover_load_3d_mean / efficiency_signed_3 / exposure_after_ref（后者自 T6.0 冻结
  daily master，PIT 列）。

## 2. 路径地图（VAL 与 DEV 一致方向；节选自 report_data.trajectory_extracts）

**按 type 的分层形态**（C701，R1 措辞修正）：
- **NO_RECOVERY**（"冷处理"）：**稳定深 DD** 形态——VAL 中位 ~0.096 略低于 severe
  （0.105），DEV 自 R+2 起 ~0.109-0.112 略高于 severe；两段共同特征是 DD 较深且窗内
  变化较小（而非稳定处于 severe 界某一侧）；换手 load ~0.97（低于 RECOVERED 组），
  exposure 中位 0.062——近乎清仓观望；
- **RECOVERED_ADD**（"修复-回吐"）：dd 先快速修复（VAL R+3 中位 0.014）再随窗尾
  扩大（R+40 0.101，逼近 severe）；价格中位 R+5 达 +1.0% 后 R+40 回到 −1.5%；
- **FAILED_EXIT**（DEV，VAL 数量不足）：dd 最深（R+1 0.132 → R+40 0.157），换手
  R+10 后塌缩至 0.76——量枯退出形态；
- **CENSORED**（418）：dd 浅（0.012-0.087）、exposure 低（0.25-0.48），窗内未终局。

**RECOVERED_ADD 内部 FR vs clean 分岔**（C702，纯记录）：
- 价格：R+2 起中位分岔——VAL clean R+3/R+5/R+40 = +1.7%/+3.1%/+1.8% vs FR
  −0.3%/−2.0%/−5.4%（DEV 同向：+1.7%/+3.3%/+0.5% vs 0.0%/−1.9%/−6.3%）；
- DD：R+40 FR 中位越过 severe（VAL 0.117 / DEV 0.128），clean 未越过（0.089/0.093）；
- 换手：**early-hot 结构**（R1 措辞修正）——FR 在 R+1/R+2 中位更高（VAL R+1
  1.358 vs 1.186）；DEV 后续维持 FR>clean，但 **VAL 自 R+5 起方向反转**（clean 1.548
  vs FR 1.299）——换手路径并非"FR 全程更热"；
- **再次强调：本阶段不评估任何变量作为真假恢复判别的有效性**——尤其换手的
  early-hot 结构与段间方向不一致（DEV 维持 vs VAL R+5 后反转）正说明 T7.2 不能拿
  T7.1 的视觉印象直接造规则，必须按 DEV-only discovery 走。

**再暴露的时序**（C703）：clean 组 exposure 中位峰在 R+5-R+10（VAL 0.938/0.959），
窗尾系统性回落（R+40 0.623）；FR 组峰值显著更低（VAL ~0.5）且回落更快——
现有 policy 的 ADD 行为本身也呈组间路径差异。

## 3. Gate

`t7_1_gates.json` 全 PASS：G1 lineage（4 输入 sha 对 manifest）→ G2b T7.0 产物
不可变（5 products）→ G8 分组覆盖守恒（1,176 行结构断言）→ **G20 描述纪律**
（源码/report/parquet 无检验机器：cluster_boot_diff/Holm/p_value 键形态扫描；
否定句散文豁免）→ **G21 中位重放**（60 cells 从冻结事实层独立重算，重放基准用
与 build 相同的冻结 point-estimate 定义 STATS['median']=wmedian，0 mismatch）→
**G21b 双 cluster CI**（两套 CI 字段齐备且标签正确）。

**R1 审计修正**（不改 grouping/point estimator/不加检验；中位数逐位不变）：
①bootstrap lineage：初版 runner 只向 cluster_boot_level 传入 stock_code，与
report/manifest 宣称的 {stock_code,T0_date} 双 cluster 不符——现生成两套独立 CI
（ci95/ci95_t0date，独立 SeedSequence 子流），G21b 强制校验；②C701 的 NO_RECOVERY
描述从"全程稳于 severe 下方"改为"稳定深 DD"（VAL 略低/DEV R+2 起略高，共同特征是
深且变化小）；③C702/报告的 FR 换手描述改为 early-hot + 段间方向差异（VAL R+5 后
反转），不再写"全程更高"。

过程记录（诚实）：G21 首版用 np.median 作重放基准，45/60 "mismatch"——根因是
**重放 est 定义与 build 不一致**（wmedian 的 repeat-expanded 分位插值 vs np.median
的偶数平均），非数据错误；对齐定义后 0 mismatch。G20 首版误伤身份声明散文中的
否定句（"no p-values"含裸词），改为标识符/调用形态扫描。by_type 初版漏 CENSORED
第四类（418 cycles），G8 分区断言抓出后补组。

## 4. 边界与下一步

- 本报告所有分组差异均为**无条件中位轨迹**的记录；不含条件分析、不含阈值、
  不含规则形态——T7.2 才第一次允许在 DEV 上问"哪些结构可能值得形成规则"。
- claims：C701/C702/C703（全 descriptive，见 `t7_1_claims.json`）。
