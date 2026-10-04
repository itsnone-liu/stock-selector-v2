# CD-1A — Sector Data & PIT Feasibility · Final Report

*Census: `cd1a_census.json` · Manifest: `cd1a_data1_manifest.json`（5430 文件 sha256）· 预注册: `cd1a_preregistration.json`（sha 10b9059a…）*
*Scope 遵守：无市场结论 · 无板块排序 · 无 CD-2 生产 · 无伪 PIT 修补*

## G-CD1A-1 Sector Feasibility Gate：**PASS（带显式降级）**

| # | 条件 | 结果 |
|---|---|---|
| c1 | 历史可用 membership | ✅ **v1-static-declared**（声明式静态分类，非历史 PIT，change_frequency=UNKNOWN，每个产物强制携带声明） |
| c2 | 至少一个经济粒度 support 合格 | ✅ **L2_csrc（证监会 83 大类）**；L1 边缘失败；L3 覆盖失败（见下） |
| c3 | 全市场日线覆盖同窗口 | ✅ 5430 文件（5223 在市 + 207 退市救回）≥ 97% 阈值；窗口 2021-01-04→2026-09-30（1393 交易日并集） |
| c4 | sector portfolio 确定性重建 | ✅ 固定板块 C39：666 成员、1392 天、双跑 sha 字节一致 |
| c5 | provenance 完整 | ✅ 每股 source+fetched_at 内嵌 + 5430 文件 sha256 manifest |
| c6 | 无未来标签回填 | ✅ 334 只 NO_CLASSIFICATION fail-closed；128 只退市股"源无数据"如实记录，永不猜 |

## 三级 Census 结果（全量 DATA-1）

| 层级 | 板块 | 股票覆盖 | 中位成员 | 单股板块 | 小板块<10 | 长空窗 | 判定 |
|---|---|---|---|---|---|---|---|
| L1_csrc | 19 | **99.94%** | 88 | **5.26%** ⚠️ | 15.8% | 0 | **边缘失败**（单股板块略超 5% 阈值：19 门类中 1 个） |
| **L2_csrc** | **83** | **99.94%** | **25** | **2.41%** | 26.5% | 0 | **PASS — 生产粒度** |
| L3_sina | 49 | **49.0%** ❌ | 40 | 0% | 8.2% | 0 | **覆盖失败**（新浪仅分类 2998/5223 股） |

- 全部层级：83/83 与 49/49 板块都有日线数据；板块级日期覆盖区间完整（2021-01-04→2026-09-30）；**零 >20 交易日长空窗**（唯一例外：L3"次新股"从 2025-10 起，语义即如此）
- median sector daily member fraction：L1/L2 = 1.0（每板块全成员有日线）；L3 = 0.98

## 生产粒度裁定（CD-1A 范围内）

- **生产用 L2_csrc**（83 大类，中位 25 成员，全市场覆盖）
- L1_csrc：**显式降级**记录（若未来 taxonomy 升级可重评）
- L3_sina：**显式降级**记录——细分粒度受分类源覆盖限制，非 support 本身问题；未来若获得全市场细分分类（历史化申万等），按预注册规则**整体替换** taxonomy，不合并不修补
- 混合粒度（用户裁定允许的形态）当前体现为：L2 生产 + L1/L3 降级

## 生存者偏差防线（数字）

csrc 快照 5555 − 在市 5223 = 335 delta：**207 只退市股已救回**（有完整日线，如 600001 等），128 只源无数据（极老退市股，fail-closed 记录在 `_delta_log.json`），3 只新上市补入。census 与未来 CD-2 漏斗必须包含退市股。

## DATA-1 已声明缺口（fail-closed，不伪造）

`amount` / `turnover_rate` / `free_float_market_cap` / `st_flag` 四字段腾讯源不可得——所有依赖成交额加权/换手/流通市值/ST 过滤的组件必须等待 EM 解封补抓或新源；量加权（volume-weighted）可作为声明的 model_derived 替代。

## 结论

> **"细分板块资金选择"作为 Market→Stock 中间层的数据基础，在 L2 粒度（证监会 83 大类）上成立；在静态声明的分类语义下可确定性重建 sector 序列。**

按预注册 on-pass 分支：**CD-1B（PIT Sector Infrastructure）可以被提出，等待用户 GO**。CD-1B 第一版四个核心轴（Relative Performance / Participation / Breadth / Concentration）的 membership 输入 = L2_csrc v1-static；amount 依赖轴（participation 的成交额份额）在缺口补齐前用 volume 替代并声明。

**全局状态**：`CD-0 FROZEN · CD-1A COMPLETE (G-CD1A-1 PASS w/ downgrades) · CD-1B 提出待 GO · CD-2 NOT STARTED · CSR-8: H IMMUTABLE / I FROZEN / J CLOSED / K NOT STARTED`
