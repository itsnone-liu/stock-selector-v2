# CF-IS 成交额口径核查

## 结论

用户提出的5000亿附近到20000亿以上规模变化，可用本地TDX市场统计amount序列核查，不需要重建全市场个股历史。它是成交活跃度而非净流入；范围未独立确证，称TDX统计成交额代理，不称官方沪深完整成交额。

## 三类不可混用的字段

1. `data/cf/derived/atoms/l4_history.jsonl`：1269行20210802..20261029，前60行历史不足；1209有效行只有金额比值，没有绝对金额。`src/stock_selector/cf/atoms.py` replay_l4读取880005 amount但只输出`amount_ratio20`=当日金额/此前20日中位数。不能拿该比值当元，也不是20日均值比。
2. `data/cd/sector_axes/l1_market_axes.json.gz`：1159日2022-01-13..2026-10-29。`scripts/cd45_market_regime.py`读取各股unadj[5]相加为vol，`part`是当天成交量/含当天20日均量；不是成交额。daily_fullmarket producer明确schema `[date,o,c,h,l,volume]`，amount缺失。实际个股文件历史覆盖变化，不是交易所每日完整市场普查。
3. `/root/tdx_data/vipdoc/sh/lday/sh880005.day`：32字节记录，amount为第6字段float；项目读法见`src/stock_selector/cf/atoms.py:32–42`。收盘字段是上涨家数，不是指数价格！仅取amount用于市场成交额描述，单位元；二进制浮点有舍入，不伪称精确官方金额。ETF/北交所是否包括仍待独立验证。

已存项目早期探针`docs/cf/cf1a_probes/20261015_evening.md`记录此市场统计的金额量级；外部eltdx文档`https://electkismet.github.io/eltdx/helpers/全市场统计/`提供880005对应total_amount语义的辅助线索，不作为范围官方确认。

## 独立交叉核对限制

搜索找到2024-08-13沪深4773亿元、2024-09-30沪深约2.59万亿元新闻摘要；正文抓取本次失败，不能作已核实精确来源。TDX对应约4799/26115亿元，存在范围或源差异，不能将两者强制相等。当前足以描述自身序列约4–5倍扩张，精确沪深口径应另核，不影响保留原始数值。

完整日/月轨迹、覆盖和散列由`is2c_turnover_trajectory.py`生成；后续研究固定使用同一序列比较，不能前期用沪深后期用全市场混拼。
