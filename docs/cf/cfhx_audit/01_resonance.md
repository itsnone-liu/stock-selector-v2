# CF-HX-2 审计记录 #1：OrangesHuang/Resonance

*审计员:* subagent d8a9e49e · *日期:* 2026-10-16 · *仓库:* /tmp/cfhx/Resonance（只读）

## CF-HX-2 标准字段

| 字段 | 值 |
|---|---|
| source | 腾讯日K(qfq/bfq 双口径,~640根/次→850天分块)/腾讯实时/新浪降级；SSE commonQuery 份额(**与 CF 官方主源同一接口**)+SZSE akshare；东财-雪球-akshare 三级成交额链；akshare 两融 |
| field | 日K/实时盘口/ETF份额(TOT_VOL 万份→亿份)/两市成交额/融资融券/交易日历/复权因子 |
| start/end | 份额=交易所官方深度(SSE 2012+/SZSE 2016-12+,与 CF 底座一致)；日K~850天/次分块可回溯更早 |
| frequency | 日频为主；盘中 30s APScheduler(asyncio.to_thread)+U型量能修正+300s 成交额轮询 |
| official/derived | 官方(交易所)为主，腾讯/东财/雪球=第三方行情，全部行为代理 |
| PIT status | **无 available_at 合同**。隐性流程：份额 T+1 回溯拉取、日期匹配才写当日行、融资 21:00 二采、前端 5 日修订缓冲、回测次日成交。**fail-open(缺数→灰灯)而非 fail-closed** |
| license | **无 LICENSE 文件**（git 仅 1 commit）→ 默认版权保留：**代码不可复用，只能借鉴思想自行实现**；数据=未授权公开接口抓取 |
| identity attribution risk | **高（但可剥离）**：风险集中在命名/文案/策略豁免/文档层（README"国家队在买卖"、Layout"中央汇金监测"、strategy BIG_BUY_YI=10亿"国家队长枪"豁免、pp≤50/≥95 事后拟合翻转阈值）；**核心计算层(factors/composite/core 五灯)基本是行为语言(吸筹/出货/申赎)，可保留思想** |

## 对 CF 的价值裁决

- **架构可借鉴**（自行实现）：填充槽台账（trade_calendar *_ok 四列"应有 vs 实际"）、幂等日期断点（库内已有跳过，非 checkpoint 文件）、分块+SEED_MIN_BARS=20 暖机前推、三级降级链、双基准取强份额概率、证据链(method/formula/thresholds/reason)、U型量能修正
- **数据交叉验证价值**：SSE 份额接口与 CF 主源同一（互相印证）；其"ETF 份额 T+1 发布"结论与 CF-1A 待定案的采样互证
- **禁止引入**：身份归因层（全部）、事后案例拟合阈值（违反 CF"看过结果禁调阈值"）、无 PIT 合同数据流、fail-open 灰灯（CF 必须 fail-closed）
- **教训记忆**: mem_mva7im4g_8c2e43（pending）

## CF-HX-4 语义证明门初判

数据层=同官方源可对账（进 CF-HX-3 hash 对账）；方法层=思想借鉴不计入数据；归因层=永禁。
