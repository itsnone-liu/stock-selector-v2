# T7 Policy Amendment Design（Freeze 前设计材料——不含 VAL/CONF 任何信息）

> 目的：把 T7.2 冻结的 DEV 素材摆成 policy 表达选项 + 交换率三口径，供 Amendment
> Freeze 拍板。**本文件不修改 contract、不打开 VAL/CONF**；规则写死后的独立
> Freeze commit 才是 T7.3b 验证的前提。数字全部来自已冻结产物
> （`t7_2_cells.parquet` / `t7_2_bins.json` / T7.0 outcomes，DEV only）。

## 0. 目标函数与预注册常量（contract 已冻结，此处仅引用）

- 核心问题："我们愿意牺牲多少真实 recovery 的早期参与机会，来减少一次错误再扩张？"
- False ADD：anchor=policy_add_day，W_fa=10；Missed Recovery：anchor=recovery
  opportunity（cycle clock）；两 clock 分离已入 gate。
- Delay primary N=3（curve {1,2,3,5} 全报）；checkpoints 决策可用 {R+1,2,3,5}。

## 1. 冻结素材

- 机械 candidate：**仅 max_bounce_R5**（FR 目标 hi−lo=−0.299，双 cluster CI 不含 0
  且 Holm reject ×2）。vol_load / turnover 不显著（est −0.048 / −0.021，双 CI 含 0）。
- DEV tertile 边界（`t7_2_bins.json`）：
  - max_bounce_R5：q1=**−0.01875**，q2=**+0.01801**
  - vol_load@maxbounce：q1=0.8967，q2=1.5918
  - turnover@maxbounce：q1=0.8930，q2=1.4688
- bounce 边际（DEV，27-cell 聚合）：lo(n=1255)：FR 率 62.1% / TR 率 5.2%；
  mid(n=1254)：FR 59.5% / TR 17.6%；hi(n=1255)：FR 32.3% / TR 51.2%。

## 2. 交换率三口径（DEV 算术，不做推断）

被 veto 的 FR 与被错过的 TR 的单位价值口径：

- **口径 A（cycle 数）**：每错过 1 个 TR 规避几个 FR；
- **口径 B（MFE 上行 gap）**：规避一个 FR 的"少亏/少折腾"≈ clean−FR 的 MFE 差
  （**+6.65pp**）；错过一个 TR 的损失≈ TR−no_TR 的 MFE 差（**+14.45pp**）——
  TR 上行是 FR 节省的 **2.2 倍**；
- **口径 C（MAE 下行规避）**：FR 的 MAE 比 clean 深 **4.67pp**（−9.57% vs −4.89%）
  ——规避 FR 同时规避其逆行波。

| 切割 | FR 规避 | TR 错过 | A: cycle 比 | B: 上行交换 | C: 下行规避 | B+C 合并 |
|---|---|---|---|---|---|---|
| **@q1**（bounce≤q1 veto ≡ bounce>q1 才 ADD） | 105（6.8%） | 65（1.7%） | **1.62 : 1** | 7.0 vs 9.4（0.74x，净 −2.4） | +4.9 | **+2.5（小幅正）** |
| **@q2**（bounce>q2 才 ADD） | 368（23.9%） | 286（7.6%） | 1.29 : 1 | 24.5 vs 41.3（0.59x，净 −16.8） | +17.2 | +0.4（近零） |

读法（如实）：**任何 bounce 切割在纯上行口径（B）下净负**——TR 的上行太大；
只有合并下行规避（C）后 @q1 才勉强转正。这提示 bounce 条件的定位应是
**风险削减条款而非收益增强条款**，与 frontier 双轴（false-ADD risk ×
recovery upside）而非单轴一致。

## 3. 政策表达选项（Freeze 需拍板的具体规则）

机械发现 → policy 表达有两条不等价路径（同一 ADD 集合，clock/语义不同）：

- **C1 = Repair confirmation @q1**：A 的 amendment——ADD 评估延至 **R+5**（因
  max_bounce_R5 到 R+5 才完整可知），当且仅当 `max_bounce_R5 > q1(−0.01875)` 允许
  ADD；R+5 前不 ADD；未确认则本 cycle 放弃 ADD（保持 REDUCE 后仓位）。
- **C2 = Strong confirmation @q2**：同上但阈值 q2(+0.01801)。
- **D1 = Weak-bounce veto @q1**：数学 ADD 集合与 C1 相同，表达为"A/B 决策时点
  到达后，若 bounce≤q1 否决本次 ADD"——与 C1 的差别在 clock 语义（C=等待确认
  最多到 R+5；D=否决式）。**建议 Freeze 二选一**（C1 或 D1），不重复注册等价规则。
- **D'（原 contract 的 hot-bounce veto 方向）**：DEV 无支持（高 bounce 组 FR 最
  低 32.3%——veto 高 bounce 在 DEV 方向相反）。若保留 D family 空位，其条件只能
  来自非 bounce 维度且无 DEV 证据——**建议 D family 留空（不注册）**，避免无证据
  规则进入验证。

## 4. 数据备注（Freeze 时须记录）

- `bh_R0_H40` 在 outcomes 表几乎全 NaN（DEV 仅 10/3,764 非空）——不可用作成本
  口径；本设计用 T7.0 自产 `mfe_after_r0` / `mae_after_r0`（全量无缺失，窗口
  R+1..R+40 内口径）。
- MFE/MAE 是窗口内极值 proxy：不捕捉可达性（不能卖在顶/买在底）；交换率数字
  是**DEV 描述性算术**，不是对 VAL 表现的预测。

## 5. 待您拍板的清单

1. **C1 / C2 / 都不 / 都要**（curve 选项：contract 允许 B 的 delay curve {1,2,3,5}
   全报；C 可同样报 q1/q2 双阈值 curve 作为 secondary，primary 单选）；
2. C 与 D1 二选一的表达（建议 C1，confirmation 语义与 False ADD 的
   policy_add_day clock 更直接）；
3. D family 是否留空（我的建议：留空，理由如上）；
4. 交换率口径的权重表态：若您认为口径 B（纯上行）应主导，则 bounce 条款整体
   不应进入 primary（B 口径净负）；若 B+C 合并口径可接受，C1 立得住为
   risk-reduction 条款。

拍板后我将起草 Freeze commit：contract 增补 `policy_amendments` 块
（规则文本 + 阈值 + bins sha + 本设计文档 sha），早于任何 VAL/CONF 验证产物。
