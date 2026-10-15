# CL-R6 数据源普查（G0 生死门）— 进行中

环境：akshare 1.18.88 @ /tmp/aksy（PYTHONPATH，规避主环境 numpy/pandas 二进制不兼容）。日期：2026-10-15。状态：**首轮探测完成，未终裁**。

## Margin 轴（初判：SUPPORT 有望）

- `stock_margin_sse(20240901–20241015)` → 25 行日线，列含融资余额/融资买入额/融券余量金额，单位=元（827,842,917,705 ≈ 8.28e11 元 ✓ 量纲合理）；
- 官方源（上交所），收盘后发布语义清晰（available_at=T close after）；
- 待核：SZSE 对应接口、历史深度（目标 2018 起）、2019-10 融资标的扩容/2023 融券新规等制度断点表。

## Funding 轴（初判：REVISION_CONTAMINATED 风险确认存在）

- `macro_china_money_supply`：225 期月度（2008-01 起），M2/M1/M0 水平+同比+环比；`macro_china_shrzgm`：136 期月度社融增量（含"非金融企业境内股票融资"子项——此子项同时是 Supply 轴候选原子量）；
- **两接口均无发布日期列，值为最新修订版** → vintage 不可恢复；
- 出路（未验证）：央行官网发布日历/新闻稿逐期重建 available_at（工作量 ~108 期，可行性待核）；不可行则 Funding 轴按草案 §2 判 UNSUPPORTED 或显式 REVISION_CONTAMINATED 降级使用。

## EquityFlow/ETF 轴（探测被超时截断，待重探）

- `fund_etf_fund_info_em("510300")` 可达但分页慢（~176 页 tqdm，120s 未完成）→ 需改用交易所源或按年分拉重探；份额（shares）字段存在性、历史深度（目标 2018）未确认。

## Supply 轴（未探测，预期最弱）

- 解禁队列接口待探；关键判据=能否恢复"历史 T 时点已知的未来解禁"（公告锚）而非回看终值。

## 第二轮探测（2026-10-15 续）

- **Supply 轴关键判定**：`stock_restricted_release_queue_em` 返回**回看终值记录**——含"实际解禁数量"与"解禁前/后 20 日涨跌幅"（后者本身即未来函数字段，任何 panel 直接引用即 look-ahead 污染）。解禁日（限售到期）虽在发行时点公开可知，但 PIT 重建"历史 T 已知供给"必须走公告锚（上市公告书/定增公告），当前接口**不足以支撑** → Supply 轴初判 **UNSUPPORTED-for-PIT**（除非另寻公告源，"失败就失败"）。
- **Margin 深度**：SSE 2018-01-02 起日线确认 ✓；SZSE 接口可达但单日粒度查询（单日 1 行，全历史需 ~2200 次调用，自动化可行）。
- ETF 份额历史：东财 spot 接口 502、fund_info 分页超时——**仍未确认**，需换路（交易所源/按年分拉）。

## 下一步（goal 轮内继续）

1. 重探 ETF 份额（按年/交易所源）+ 解禁队列接口性质判定；
2. Margin 沪深双所 + 历史深度 2018 验证；
3. 央行发布日历重建可行性抽查（3–5 期）；
4. 汇总逐轴 G0 裁决表（SUPPORTED / REVISION_CONTAMINATED / UNSUPPORTED）。

（配套：R6-0 Evidence Atlas 由后台子代理调研中，产出后并入 `CL_R6_EVIDENCE_ATLAS.md`。）

## G0 逐轴终裁表（2026-10-15，PRE-RESEARCH 阶段结论）

| 轴 | 判定 | 依据 | 说明 |
|---|---|---|---|
| **Margin** | **SUPPORTED** | SSE 官方日线 2018-01-02 起实测 ✓（单位元）；SZSE 可达（单日制查询，可自动化） | available_at=T close after 语义清晰；断点表（标的扩容/融券新规）待 R6-1 合同化 |
| **Funding** | **REVISION_CONTAMINATED / available_at 可重建** | akshare 值=最新修订版、无发布日期列；抽查证实发布日可由带日期官方新闻档案逐期重建（2020-09 社融=2020-10-14 发布，cnfin/人民网/央广多源一致） | ~108 期人工/半自动重建可行但费工；使用时必须显式标记"修订污染"，不得假装当时值 |
| **EquityFlow/ETF** | **PARTIAL——价格/成交深、份额未确认** | hist_sina 510300 回溯至 2012-05-28（量额 ✓）；份额序列（Flow 构造必需）接口超时/502 未落定 | 份额是 ETF NetFlow 的分项（ΔShares×NAV），无份额则该通道不成立；R6-1 前需交易所源人工核查 |
| **Supply** | **UNSUPPORTED-for-PIT** | 解禁接口=回看终值（含解禁前后 20 日涨跌幅未来函数字段）；公告锚源未在 akshare 内 | "历史 T 已知供给"重建需上市公告书/定增公告级数据；按预注册"失败就失败" |

**汇总**：四轴中 1.5 轴过门（Margin 全、Funding 半）、1 轴待定（ETF 份额）、1 轴判死（Supply 现有源）。与 Evidence Atlas 外部证据强度（域 4 融资/域 3 ETF 最扎实）交叉对照：**外部证据最强的两域恰好是数据可行性最好的两域**；Supply 轴外部证据中等但数据判死——若维持判死，R6-v1 范围收缩为 Funding(修订污染)/ETF/Margin 三轴 + Absorption（本地行情可构造）。

配套：`CL_R6_EVIDENCE_ATLAS.md`（38 源，7 域机制卡）已归档。


## 裁决后修订（2026-10-15 用户裁决，覆盖上表轴地位）

- Supply：UNSUPPORTED-for-PIT → **正式出局 v1**（Future Ideas）；
- Funding：REVISION_CONTAMINATED → **FundingContext 降级保留**（E1 上限，三冻结边界见预注册 §3.5）；
- ETF 份额交易所官方源核查：**授权执行中**（九项清单，本文件下节记录）。

## ETF 官方份额源核查结果（2026-10-15，授权执行）

- **SSE `fund_etf_scale_sse(date=YYYYMMDD)`**：按日查询官方接口，逐基金当日份额（单位=份）+ETF 类型；**深度实测至 2012-01-05**（2012=23 只/2015=61/2018=88/2025=593）。按日查询天然返回**当日存在基金全集**=自然 PIT；
- **SZSE `fund_scale_daily_szse(start,end,symbol='ETF')`**：日期区间官方接口，逐基金逐日份额；**2018-01-05 实测 ✓（585 行/11 交易日）**，2015 返回空（深度界于 2015–2018 间，未精确定位）；
- **裁决：ETF 轴升级为 SUPPORTED（官方双所历史份额，2018+ 全覆盖）**。待核遗留：发布时点（T 晚 vs 次晨，需一次实时观察定案）；SSE ETF 类型标签为当前口径（分类 PIT 细节）；清盘/合并的退出日在按日查询下自然正确；
- R6-v1 轴最终形状：**FundingContext（降级）+ EquityFlow（ETF 官方+Margin 官方）+ Absorption（本地构造）**。
