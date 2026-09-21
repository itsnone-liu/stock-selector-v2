# ADJUSTMENT_V1 源实证报告 · 第二部分（严格门禁复验 v3）

**日期**: 2026-09-21 · **程序**: `scripts/audit_adjustment_v3.py`（v2 的静默放行修复版）
**结论**: **PASSED，严格门禁退出码 0**；故障注入测试 5/5 全部拦截；待人工公司行动核对完成（见 §6 验证例外）后可升级 `adjusted_verified`。

历史版本保留：v2（`ADJUSTMENT_V1_FETCH_AUDIT_V2.json`，存在 G1 自动重冻结/G4 空 dict 放行/G5b 加载失败 continue 绕过/G6 确认口径错误，已被 v3 取代，留作审计轨迹）；权威结果 = v3（`ADJUSTMENT_V1_FETCH_AUDIT_V3.json`）。

---

## 1. 第二轮审查缺陷修复对照

| 位置 | 缺陷 | v3 修复 | 故障注入验证 |
|---|---|---|---|
| G1 | universe 变化自动重新冻结；n_ok+n_fail 恒等于 manifest 长度 | 审计只读；清单/扫描不一致直接失败；校验 frozen 自身 codes_sha256；**要求 n_fail==0** | 注入E（改冻结清单 code 不动哈希）→ G0/G1 拦截 ✓ |
| G4 | TDX 缺文件返回空 dict，零交集放行 | 缺文件 → `missing_local_files` 计 gate_failures；新增覆盖率门禁（对账日/窗口日 ≥99%） | 注入C（删 sh.600000.day）→ G4 拦截 ✓ |
| G5 | u×F==h 属代数恒等式 | 保留但标注 disclaimer（恒等式级自检，不构成独立验证）；独立对账由 G5b 承担 | — |
| G5b | 源加载失败 `continue` → 全量绕过；无行数完整性 | 加载失败计 gate_failures；新增 `validated_rows/skipped_rows/missing_keys/duplicate_keys/extra_keys`，**validated==expected 严格相等** | 注入A（篡改F）→ row_mismatch 拦截 ✓；注入B（删行）→ validated<expected 拦截 ✓ |
| G6 | `action_days∩sina` = sina 事件数本身，非 bs 候选确认数；sina 读取失败静默跳过 | 候选/确认/未确认分离：`bs_candidates / bs_confirmed_by_sina（bs候选日逐日∈sina事件）/ bs_unconfirmed_detail / sina_only_events`；sina 加载失败 → `sina_load_failures` 计 gate_failures | 注入D（删 sina 文件）→ G6 拦截 ✓ |
| 根哈希 | 冻结三哈希存而不用 | G0 只读重算四项基准（frozen codes_sha256 / per_stock 根 / fetch_manifest / factor_table）逐一 == 冻结记录；未记录字段显式标 `not_recorded` 不静默通过 | 注入E 拦截 ✓ |

故障注入测试程序：`scripts/test_fault_injection.py`（8 只真实股沙盒，基线 PASSED + 5 类注入全 FAILED 且命中对应门禁）。

## 2. 门禁结果（全量真实快照，ADJUSTMENT_V1_FETCH_AUDIT_V3.json）

| 门禁 | 结果 |
|---|---|
| G0 冻结基准 | **✓** 四项哈希全对 |
| G1 universe 闭合 | **✓** 5240==manifest==ok；n_fail=0；未尝试/多余=0 |
| G2 全量文件 SHA256 | **✓** 5240/5240 |
| G3 结构 | **✓** 0 异常 |
| G4 TDX 价格 | **✓** 0 不符；缺文件 0；**覆盖率 6,115,261/6,115,261 = 100%** |
| G5 浮光重建 | **✓** 0（定位：恒等式自检） |
| G5b 因子表 | **✓ validated 6,663,146 == expected 6,663,146**；skipped 0；missing/duplicate/extra keys 0 |
| G6 候选/确认 | **✓** 候选 23,022；**sina 确认 23,005；未确认 17（全部属于已裁决排除的 14 只，清单外未确认=0）**；sina_only 1,421（小额分红）；段内漂移 0；sina 加载失败 0 |
| G7 OHLC 抽验 | **✓** 0/60 |

技术勘误记录：G5b 容差建模——`%.6f` 舍入误差上界恰为 5e-7，边界行（源值第 7 位小数=5）在浮点比较下翻转；容差取 5.0001e-7（舍入上界+浮点余量），实质未放宽。

## 3. G6 假漂移裁决实录（v2 方法论记录，v3 继承）

初版单源分段报 7 段"漂移"（1.2~1.95e-4）。逐段 sina 独立源对照 7/7 命中微分红事件（跳变 <2e-4 候选阈值），sina 因子与 bs F 吻合至第 6 位小数——真实公司行动累积而非数据缺陷。v2 起改双源分段（行动日=bs 全候选∪sina 事件日），全市场段内漂移归零。

## 4. 独立第二源验证（引用第一部分跨源审计）

- **C1**: bs↔sina 5237 共同股，事件日全等 3,848 只；差异主体为 1,421 个 <2e-4 小额分红；material 真错位 17 事件/14 股（已裁决排除，v3 G6 未确认候选与之精确对应）
- **C2**: bs F 段值 vs sina 累计因子 4,658 只段内恒定；tx 因子 ~5% 连续漂移 → 降级价格对照源（价格 5236/5237 全对）
- **C3**: 30 只分层样本表（`ADJUSTMENT_V1_CROSS_AUDIT.json → c3_sample`）

## 5. 冻结物与根哈希（G0 已逐一核对）

```
config/universe_frozen.json
  count                 = 5240
  codes_sha256          = 521e146dd838f959…
  per_stock_root_sha256 = 783e5cd849eb486eba2aff854e418c4718ff3406e2ff9ceb5f4bb8aa7c1986d6
  fetch_manifest_sha256 = f16b764e6a3358269eef229dde06f9ae37df8fd8a20ac6852fc39f9ceeade6b3
  factor_table_sha256   = e9f46fce11e8870f…
```
原始 5,240 个 json.gz 不入 Git；逐文件 SHA256 在 manifest（Git 内），根哈希在冻结清单，任何人可离线重算对账。

## 6. 验证例外（未完成项，明确列示）

**冻结规范 §5.2 要求的人工公司行动样本（分红/送转/拆分 ≥30 只，股数与价值守恒对照）未完成。** 本报告采用的双独立源（bs↔sina）+TDX 三角验证可交叉印证事件日与因子一致性，但**不等价于**人工公告核对（无法验证股数/价值守恒、无法发现两源同错的系统性偏差）。此例外在人工核对完成前持续有效，是 `adjusted_verified` 的附带条件而非已完成项。

## 7. 结论

- 全量完成性/文件完整性/行级对账：**结构可证明**（G0/G1/G2/G5b，故障注入验证拦截有效）
- 静默放行路径：**已封死**（G1 不改写冻结、G4 缺源失败、G5b 加载失败计失败、G6 sina 断裂计失败）
- 程序质量：v3 通过审查要求的全部修正点；数据本身零缺陷发现
- `adjustment_v1` 升级 `adjusted_verified`：**程序侧条件满足**，附带 §6 人工核对例外
