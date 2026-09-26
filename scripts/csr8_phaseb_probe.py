#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase B channel probe — SINGLE SOURCE OF TRUTH generator.

Runs every endpoint probe and writes CHANNEL_PROBE.yaml directly (no
hand-authored report drift). Status ladder (audit fix v2):
  SMOKE_OK                 interface returns data
  CONTENT_OK_PIT_PENDING   fields usable but publication/available_date NOT provable
  SMOKE_OK_OPTIONAL_REFERENCE  works but current-snapshot only (cannot serve PIT)
  PENDING_RETRY            network/limit failure, endpoint exists
  INTERFACE_GAP            no akshare interface
  SOURCE_DESIGN_REQUIRED   must be built from official archives, not an API retry
  UNPROBED                 not yet attempted (explicitly registered)
Counts: channel_family_count / endpoint_count / evidence_id_count kept distinct.
"""
import json, traceback
from pathlib import Path
import pandas as pd
import yaml

OUT = Path(__file__).resolve().parents[1] / 'output/research/csr/08_pilot_cases/phase_b'
OUT.mkdir(parents=True, exist_ok=True)

def P(name, layer, family, evidence, status, fn, fields=None, note=None, success_status=None):
    return dict(name=name, layer=layer, channel_family=family, evidence_ref=evidence,
                status=status, fn=fn, fields=fields, note=note,
                success_status=success_status or status)

PROBES = [
    P('rt_margin_market_total_sh', 'rt', 'margin', 'E-MKT-02 (market agg)',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').macro_china_market_margin_sh(),
      ['日期', '融资买入额', '融资余额', '融券余量', '融券余额', '融资融券余额'],
      '市场层汇总；不能给 84 个股案例提供 stock-level margin evidence'),
    P('rt_margin_stock_detail_sse', 'rt', 'margin', 'E-STK-08 (per-stock)',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').stock_margin_detail_sse(date='20250919'),
      ['信用交易日期', '标的证券代码', '融资余额', '融资买入额', '融券余量'],
      'SSE per-stock 明细 1906 标的（盘后披露，T 日盘后官方可得性按 CSR-6；'
      '聚合源 timestamp 规则待 ingestion 契约）'),
    P('rt_margin_stock_detail_szse', 'rt', 'margin', 'E-STK-08 (per-stock)',
      'PENDING_RETRY',
      lambda: __import__('akshare').stock_margin_detail_szse(date='20250919'),
      None, '2026-09-26 首探连接重置（深交所域）；重跑成功即升级',
      success_status='CONTENT_OK_PIT_PENDING'),
    P('rt_margin_underlying_pool_szse', 'rt', 'margin', 'contract item: 两融标的池历史 membership',
      'SMOKE_OK_OPTIONAL_REFERENCE',
      lambda: __import__('akshare').stock_margin_underlying_info_szse(),
      ['证券代码', '融资标的', '融券标的'],
      '当日快照口径——历史 membership 需从现在起每日存档积累，不能回溯'),
    P('rt_block_trade', 'rt', 'block_trade', 'CSR-6 大宗交易 verdict',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').stock_dzjy_mrmx(symbol='A股',
                                                   start_date='20240102', end_date='20240110'),
      ['交易日期', '证券代码', '成交价', '折溢率', '成交量', '成交额'],
      "symbol='A股'（证券类别，非个股代码）；T+1 补充披露须作独立 event 不覆盖首披露"),
    P('rt_dragon_tiger', 'rt', 'dragon_tiger', 'CSR-6 龙虎榜 verdict',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').stock_lhb_detail_em(start_date='20250106',
                                                        end_date='20250110'),
      ['代码', '上榜日', '龙虎榜净买额', '龙虎榜买入额', '龙虎榜卖出额'],
      '聚合源=东财；官方交易所 T 日盘后 vs 聚合 T~T+1 须按 source timestamp 登记，'
      '无可验证 timestamp 时保守按 T+1 并登记'),
    P('rt_etf_share', 'rt', 'etf_share', 'CSR-6 ETF 份额 verdict',
      'INTERFACE_GAP', None, None,
      'akshare 1.18.97 无 ETF 历史份额专用接口；需替代源，不假装覆盖'),
    P('xp_holder_count_list', 'xp', 'holder_count', 'CSR-6 户数 verdict',
      'PENDING_RETRY',
      lambda: __import__('akshare').stock_zh_a_gdhs(symbol='20250331'),
      ['股票代码', '股东户数'],
      '东财域间歇限流；成功且必需字段齐才升级(FIELD_SCHEMA_MISMATCH gate)', 
      success_status='CONTENT_OK_PIT_PENDING'),
    P('xp_holder_count_detail', 'xp', 'holder_count', 'CSR-6 户数 verdict',
      'PENDING_RETRY',
      lambda: __import__('akshare').stock_zh_a_gdhs_detail_em(symbol='sh688686'),
      None, '返回结构异常（result None），同东财域'),
    P('xp_top10_float_holders', 'xp', 'top10_holders', 'CSR-6 十大流通股东 verdict',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').stock_gdfx_free_top_10_em(symbol='sh688686',
                                                              date='20250630'),
      ['名次', '股东名称', '持股数', '占总流通股本持股比例', '增减'],
      '报告期口径；报告期末≠可获得日——publication_date 链未证明，禁提前使用'),
    P('xp_top10_holders', 'xp', 'top10_holders', 'CSR-6 十大股东 verdict',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').stock_gdfx_top_10_em(symbol='sh688686', date='20250630'),
      ['名次', '股东名称', '持股数', '占总股本持股比例', '增减'],
      '同上：CONTENT_OK_PIT_PENDING'),
    P('xp_fund_holdings', 'xp', 'fund_holdings', 'CSR-6 基金持仓 verdict',
      'CONTENT_OK_PIT_PENDING',
      lambda: __import__('akshare').fund_portfolio_hold_em(symbol='000001', date='2024'),
      ['股票代码', '占净值比例', '持股数', '持仓市值', '季度'],
      '按基金拉取；季报披露日≠季末——publication_date 需与基金公告源 join'),
    P('xp_insider_trades', 'xp', 'insider_trades', 'CSR-6 增减持 verdict',
      'PENDING_RETRY',
      lambda: __import__('akshare').stock_ggcg_em(symbol='全部'),
      None, '东财域限流批；非接口不存在'),
    P('current_industry_snapshot_em', 'reference', 'industry', 'G5 comparator（现时）',
      'SMOKE_OK_OPTIONAL_REFERENCE',
      lambda: __import__('akshare').stock_board_industry_name_em(),
      ['板块名称', '板块代码'],
      '现时口径快照；可作为参考但与 G5 revalidation 的 PIT 需求无关'),
    P('pit_industry_table', 'reference', 'industry', 'CSR-6 契约项: 时点行业表',
      'SOURCE_DESIGN_REQUIRED', None, None,
      '必须以官方历史分类快照+变更公告构建；不依赖任何现时接口的重试；'
      'G5 revalidation 的唯一合规来源'),
]

def run():
    import akshare
    results = []
    for p in PROBES:
        row = dict(p)
        fn = row.pop('fn')
        if fn is None:
            row['rows_probed'] = None
            results.append(row); continue
        try:
            df = fn()
            if df is None or len(df) == 0:
                row['probe_result'] = 'EMPTY'
            else:
                row['rows_probed'] = int(len(df))
                cols = [c for c in map(str, df.columns)][:10]
                if row.get('fields'):
                    missing = [f for f in row['fields'] if f not in cols]
                    row['fields_missing_from_response'] = missing or []
                row['probe_result'] = 'OK'
                # AUDIT rule: nonempty is NOT sufficient — required fields must
                # all be present before any upgrade (FIELD_SCHEMA_MISMATCH gate)
                if row.get('fields_missing_from_response'):
                    row['status'] = 'FIELD_SCHEMA_MISMATCH'
                    row['probe_result'] = 'OK_BUT_FIELDS_MISSING'
                elif row['status'] == 'PENDING_RETRY':
                    row['status'] = row['success_status']
        except Exception as e:
            row['probe_result'] = f'FAIL {type(e).__name__}: {str(e)[:100]}'
            if row['status'] == 'CONTENT_OK_PIT_PENDING':
                row['status'] = 'SMOKE_OK_AT_PROBE_TIME_NOW_FAILING'
            elif row['status'] == 'SMOKE_OK_OPTIONAL_REFERENCE':
                row['status'] = 'OPTIONAL_ENDPOINT_FAILING'
        results.append(row)
    fams = {r['channel_family'] for r in results}
    evids = {r['evidence_ref'] for r in results}
    # dynamic next-action derivation: status machine, not per-round hand-writing
    NEXT_ACTION_BY_STATUS = {
        'CONTENT_OK_PIT_PENDING': None,                # no action (fields ok, PIT join later)
        'SMOKE_OK': None,                              # defensive: ladder-only states
        'PIT_READY': None,                             # defensive: ladder-only states
        'SMOKE_OK_OPTIONAL_REFERENCE': None,           # reference only, no pipeline role
        'PENDING_RETRY': 'retry (network/limit failure this round)',
        'FIELD_SCHEMA_MISMATCH': 'schema remap (column names) then re-probe',
        'OPTIONAL_ENDPOINT_FAILING': 'optional reference failing: retry or drop',
        'SMOKE_OK_AT_PROBE_TIME_NOW_FAILING': 're-probe to confirm status',
        'INTERFACE_GAP': 'alternate-source research required',
        'SOURCE_DESIGN_REQUIRED': 'standalone design item (official archives)',
    }
    next_actions = {r['name']: NEXT_ACTION_BY_STATUS[r['status']] for r in results}
    doc = {
        'stage': 'csr_8_phase_b_channel_probe',
        'generated_by': 'scripts/csr8_phaseb_probe.py (single source of truth; audit-fix v2)',
        'purpose': ('Phase B 外部数据通道可用性勘察（probe only，不落正式数据）。'
                    '状态阶梯: SMOKE_OK(接口能返回) < CONTENT_OK_PIT_PENDING(字段够用但 '
                    'publication/available_date 不可证) < PIT_READY(公告日链可证明)。'
                    '本报告只覆盖前两层。'),
        'akshare_version': akshare.__version__,
        'status_ladder': ['SMOKE_OK', 'CONTENT_OK_PIT_PENDING', 'PIT_READY',
                          'SMOKE_OK_OPTIONAL_REFERENCE', 'OPTIONAL_ENDPOINT_FAILING',
                          'SMOKE_OK_AT_PROBE_TIME_NOW_FAILING', 'PENDING_RETRY',
                          'FIELD_SCHEMA_MISMATCH', 'INTERFACE_GAP',
                          'SOURCE_DESIGN_REQUIRED'],
        'pit_rule': ('report_period_end != available_date；任何 xp 证据在 publication_date '
                     '链建立前不得进入盲标注/回测可用集；rt 聚合源无可验证 timestamp 时按 T+1 '
                     '保守处理并登记 availability_basis'),
        'channels': results,
        'counts': {
            'channel_family_count': len(fams),
            'endpoint_count': len(results),
            'evidence_id_count': len(evids),
            'by_status': {},
        },
        'next': (
            ['rt 三通道(margin/lhb/dzjy)按 84 案例窗口正式拉取——ingestion 契约先行: '
             'observation_date/source/source_record_date/publication_date/retrieved_at/'
             'available_date/availability_basis 七字段必留(observation_date 为 CSR-6 '
             '核心时间链主键,通道事件时间留 payload)',
             'XP 通道的 publication_date 链：巨潮公告 join 方案设计']
            + [f'{name} -> {act}' for name, act in sorted(next_actions.items()) if act]
        ),
    }

    from collections import Counter
    doc['counts']['by_status'] = dict(Counter(r['status'] for r in results))
    doc['next_action_rule'] = ('derived per-round from status via NEXT_ACTION_BY_STATUS; '
                               'probe result -> status -> next action (machine loop)')
    y = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)
    (OUT / 'CHANNEL_PROBE.yaml').write_text(y, encoding='utf-8')
    print('CHANNEL_PROBE.yaml written')
    for r in results:
        print(f"{r['name']:34s} {r['status']:34s} {r.get('probe_result', '-')}")
    print('counts:', json.dumps(doc['counts'], ensure_ascii=False))

if __name__ == '__main__':
    run()
