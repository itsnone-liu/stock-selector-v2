# ADJUSTMENT_V1 源实证报告 · 第二部分（严格门禁复验）

**日期**: 2026-09-21 · **程序**: `scripts/audit_adjustment_v2.py`（对现有快照复验，未重新拉取）
**结论**: **PASSED，严格门禁退出码 0**。adjustment_v1 具备升级 `adjusted_verified` 条件。

响应 2026-09-21 用户审查：5 项阻塞问题已全部结构性修复（非调参通过）。

---

## 1. 阻塞问题修复对照

| # | 阻塞问题 | 修复 |
|---|---|---|
| 1 | 无法证明全部完成（审计只遍历 manifest 已有股票） | G1：冻结 `config/universe_frozen.json`（count+codes+codes_sha256），强制 manifest 股票集合 == universe codes，n_ok+n_fail == count，未尝试/多余逐只列出 |
| 2 | 断点恢复跳过 ok 文件校验 | G2：审计独立全量重算 5240 个 per_stock 文件 SHA256 与 manifest 对账（不依赖抓取器的 done/todo 逻辑）；孤儿文件一并检出 |
| 3 | TOL_F==JUMP 致 elif 不可达；跳变≠除权日 | G6：改名 `factor_jump_candidate`；分段行动日 = bs 跳变候选(>2e-4) **∪ sina 独立源事件日**；段内漂移在确认行动日之间检查（见 §3 裁决实录） |
| 4 | 异常仍 return 0 | `status: passed/failed` + `gate_failures` 明细数组；exit 1 on failed（本次实测 0） |
| 5 | 审计不复核源文件哈希 | G2 即为全量哈希复核（拉取后损坏可检出） |

## 2. 门禁结果（docs/reports/ADJUSTMENT_V1_FETCH_AUDIT.json）

| 门禁 | 内容 | 阈值 | 结果 |
|---|---|---|---|
| G1 | universe 冻结闭合 | 集合相等 + 计数相等 | **✓** 5240==5240==5240，未尝试 0，多余 0 |
| G2 | 全量文件 SHA256 | 逐文件 vs manifest | **✓** 5240/5240 全对，孤儿 0 |
| G3 | 结构（原始列表直查：日期唯一/升序/close>0；n_rows==len(unadj)==len(hfq)；两套日期集合相等） | 全量 | **✓** 0 异常 |
| G4 | TDX 本地 close vs unadj close | 1e-4 | **✓** 0 不符（裁决排除股豁免，命中清单在报告） |
| G5 | 内部闭合 u×F==h | 1e-9 | **✓** 0 失败 |
| G5b | 因子表 factor_table.csv.gz 与源逐行对账（uc/hc/F 三项） | 5e-5/5e-7/1e-9 | **✓** 6,663,146 行 0 差 |
| G6 | 双源行动日分段后段内漂移 | 1e-4 | **✓** 0 段漂移；跳变候选 23,154（其中 132 由 sina 确认补充） |
| G7 | OHLC 抽验（分层 60 只：o/h/l×F vs hfq OHLC + low≤o,c≤high） | 1e-6 | **✓** 0/60 |

manifest 元数据补录（入审计报告 `manifest_meta`）：adjustflag unadj=3/hfq=1、fields=date,open,high,low,close,volume,amount,turn,pctChg、日期 2021-01-01~2026-09-19、baostock 0.9.30（pip freeze）。

## 3. G6 假漂移裁决实录（方法论记录）

初版单源分段报 7 段"漂移"（幅度 1.2~1.95e-4）。逐段用 sina 独立因子源对照：**7/7 全部命中微分红事件**（跳变 1~2e-4，低于 2e-4 候选阈值），且 sina 因子值与 bs F 段值吻合至 6 位小数（如 sh.603991：sina 1.0126171 vs bs 1.012617）。定性：**真实公司行动的累积，非数据漂移**；其中 3 段属已裁决排除股。修复=双源行动日分段后，全部 5240 股段内漂移归零。此实录留档防止后续把微分红误判为数据缺陷。

## 4. 独立第二源验证与公司行动样本（引用第一部分跨源审计）

- **C1（事件日对照）**: bs↔sina 5237 共同股，事件日全等 3848 只；差异 1389 只中 1421 个为 <2e-4 小额分红（bs 精度极限）、material 真错位仅 17 事件/14 股（已裁决排除）
- **C2（因子级）**: bs F 段值 vs sina 累计因子，4658 只段内比值恒定（<5e-3 口径差）；tx 因子存在 ~5% 连续漂移 → 降级为价格对照源，其 unadj 价格 5236/5237 全对
- **30 只分层公司行动对照样本**: cross_audit C3 样本表（主板/创业板/科创板/北交所分层，每股 bs/sina 事件日+因子对照，`docs/reports/ADJUSTMENT_V1_CROSS_AUDIT.json` → c3_sample）。手工逐条公告核对不在本机数据源能力内，以双独立源+TDX 三角验证替代，方法局限已在报告标注

## 5. 冻结物与根哈希（可离线验证）

```
config/universe_frozen.json
  count                = 5240
  codes_sha256         = 521e146dd838f959…  (codes 列表全量 sha256)
  per_stock_root_sha256= 783e5cd849eb486eba2aff854e418c4718ff3406e2ff9ceb5f4bb8aa7c1986d6
                          (sha256 of "code:file_sha256" 全 5240 行)
  fetch_manifest_sha256= f16b764e6a3358269eef229dde06f9ae37df8fd8a20ac6852fc39f9ceeade6b3
  factor_table_sha256  = e9f46fce11e8870f…  (output/research/adjustment_v1/factor_table.csv.gz)
```

原始 5,240 个 json.gz 文件不入 Git（体积），但逐文件 SHA256 已入 manifest（Git 内）、聚合根哈希入冻结清单——任何人可离线重算对账。

## 6. 结论

- 全量拉取完成性：**可证明**（G1 结构闭合，不再依赖"运行时扫描碰巧相等"）
- 源文件完整性：**可证明**（G2 全量哈希复核）
- 价格/因子/OHLC 一致性：**零缺陷**（G3/G4/G5/G5b/G7）
- 因子跳变定性：**候选+独立源确认制**（G6），微分红不漏不误报
- **adjustment_v1 → adjusted_verified 成立**（排除清单 24 只维持 2026-09-21 用户裁决不变）
