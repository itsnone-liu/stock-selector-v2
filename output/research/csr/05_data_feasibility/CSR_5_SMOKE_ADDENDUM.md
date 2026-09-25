# CSR-5 接口级 Smoke 附录（desk audit 的实测补充）

> 触发：用户提供 tushare token 并问"要冲积分吗"。本附录回答该问题，
> 不改变 CSR_5_DATA_FEASIBILITY.yaml 的任何评级（渠道级结论全部维持）。
> 纪律：仍属可行性审计——只探接口可用性，未落任何研究数据。
> tushare token 只进会话环境变量，不落仓库/不进 git。

## 1. tushare 实测（token 有效，积分为 0）

- token 鉴权通过（能区分"接口名错误"与"无权限"两类报错）；
- **积分为 0**：连 `stock_basic` / `trade_cal` / `daily` 的 120 分基础档都无权限——
  17 个 CSR 相关接口（daily/margin_detail/top_list/block_trade/top10_holders/
  stk_holdertrade/repurchase/share_float/fund_share/etf_share_size/
  moneyflow_hsgt/hk_hold/index_daily/fund_nav 等）全部被拒。

## 2. akshare 1.18.97 免费路径实测（同日）

| 证据 | 接口 | 结果 |
|---|---|---|
| E-STK-08 两融明细（深市） | stock_margin_detail_szse | **OK** 1,980 标的 |
| E-MKT-02 两融（沪市汇总） | stock_margin_sse | **OK** |
| E-STK-05 龙虎榜 | stock_lhb_detail_em | **OK** 86 行（当日） |
| E-STK-04 大宗 | stock_dzjy_mrmx | **OK** 16 行（当日） |
| E-STK-02 十大流通股东 | stock_gdfx_free_top_10_em | **OK**（东财聚合） |
| E-MKT-01 ETF 份额（上交所官方） | fund_etf_scale_sse | **OK** 715 只（二轮实测，与 0915 结论一致） |
| E-STK-09 解禁 | stock_restricted_release_queue_em | 接口存在（默认窗 rows=0，参数待修正） |
| E-STK-01 股东户数 | stock_zh_a_gdhs / stock_gdhs | **未确认**（1.18.97 无 stock_gdhs；个股历史接口网络断连） |
| E-STK-03 基金持仓 | fund_portfolio_hold_em | **未确认**（882 页大分页+编码报错，工程问题非权限问题） |
| E-STK-06 增减持 | stock_ggcg_em | **未确认**（东财大分页断连） |

## 3. 结论：不冲积分（现阶段）

1. **日频资金证据四类（两融/大宗/龙虎榜/ETF 份额）免费全部实测通过**——
   这是 CSR-6 PIT 审计里最关键的日频层，tushare 无必要性；
2. 十大流通股东免费通过；解禁接口存在；
3. 三个未确认项（户数/基金持仓/增减持）都是**季频或事件驱动**证据——
   非近实时大批量，官方渠道（巨潮/公告）可回补，失败模式是接口名/
   分页工程问题，不是权限墙；
4. **etf_share_size 的 8000 积分档确认不买**（官方免费源两轮实测可用）；
5. tushare 的真实价值=整理好的稳定接口（省工程量），对应的是**工程成本**
   而非数据可得性——CSR-5 的 OBTAINABLE 结论不依赖它。
   若 CSR-8 案例阶段断连率/整理量不可接受，再按缺口充最低够用档
   （多数披露类在 2000 分档；以官网档位为准，不预付高档）。

## 4. 免费路径的已知成本（如实）

- 东财系大分页接口（基金持仓 882 页、增减持）断连频繁——批量回补需要
  断点续跑与限速，工程量真实存在；
- akshare 为第三方聚合：**官方渠道交叉验证 + 本地存档**原则不变
  （CSR-5 meta 已立），免费聚合只作第一通道不作唯一事实源。
