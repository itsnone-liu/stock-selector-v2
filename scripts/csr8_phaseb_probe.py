#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase B probe — channel availability survey (no formal data landing).

Per CSR-6 contract_items_for_ingestion: rt-layer channels (margin/block-trade/
dragon-tiger/ETF-share) + xp-layer channels (holder-count/top10-holders/
fund-holdings/insider-trades) + PIT industry table.
Probe = interface existence + key fields + history coverage only.
"""
import sys, json, traceback
import pandas as pd
import akshare as ak

RESULTS = []
def probe(name, fn):
    try:
        df = fn()
        if df is None or len(df) == 0:
            RESULTS.append((name, 'EMPTY', '')); return
        cols = list(df.columns)[:12]
        RESULTS.append((name, f'OK rows={len(df)}', str(cols)))
    except Exception as e:
        RESULTS.append((name, f'FAIL {type(e).__name__}', str(e)[:120]))

# ---- rt layer ----
probe('margin_detail_sh', lambda: ak.macro_china_market_margin_sh())
probe('block_trade', lambda: ak.stock_dzjy_mrmx(symbol='000001', start_date='20240101', end_date='20240201'))
probe('dragon_tiger_daily', lambda: ak.stock_lhb_detail_em(start_date='20250106', end_date='20250110'))
probe('etf_fund_share_em', lambda: ak.fund_etf_fund_info_em(fund='510050'))

# ---- xp layer ----
probe('holder_count', lambda: ak.stock_zh_a_gdhs(symbol='20250331'))
probe('top10_float', lambda: ak.stock_gdfx_free_top_10_em(symbol='sh688686', date='20250630'))
probe('top10_holder', lambda: ak.stock_gdfx_top_10_em(symbol='sh688686', date='20250630'))
probe('fund_holdings', lambda: ak.fund_portfolio_hold_em(symbol='000001', date='2024'))
probe('executive_trade', lambda: ak.stock_em_ggcg(symbol='全部", "560878'))
probe('shareholder_change', lambda: ak.stock_ggcg_em(symbol='全部'))

# ---- PIT industry ----
probe('pit_industry_em', lambda: ak.stock_board_industry_name_em())

print('akshare', ak.__version__)
for n, st, d in RESULTS:
    print(f'{n:24s} {st:24s} {d}')
