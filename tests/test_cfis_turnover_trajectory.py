"""Turnover amount decoding, strict trailing windows and monthly fail-closed guards."""
import importlib.util
import math
import struct
from datetime import date, timedelta
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('turnover', Path(__file__).resolve().parents[1] / 'scripts/cfis/is2c_turnover_trajectory.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def record(day=20240924, amount=1.23e12, volume=123):
    return struct.pack('<IIIIIfII', day, 111, 222, 33, 99, amount, volume, 0)


def rows(n=90):
    return [dict(date=(date(2024,1,1)+timedelta(days=i)).isoformat(), amount_yuan=float(i+1)*1e8, volume=999) for i in range(n)]


def daily_dates(ds):
    return m.build_daily([dict(date=d,amount_yuan=1e12,volume=999) for d in ds])


def axes(ds):
    return [dict(date=d,breadth=.5,part=1.1,conc50=.6,eq_ret=.01) for d in ds]


def prices(ds):
    return [dict(trade_date=d,close=100+i) for i,d in enumerate(ds)]


def test_amount_not_volume_or_close():
    r = m.parse_day_bytes(record())[0]
    assert r['amount_yuan'] == struct.unpack('<f',struct.pack('<f',1.23e12))[0]
    assert r['volume'] == 123
    assert 'close' not in r
    assert m.build_daily([r])[0]['amount_yi'] > 10000


@pytest.mark.parametrize('raw', [b'', b'x', record()+b'X', record(20240230), record()+record(), record(20240925)+record(), record(amount=float('nan')), record(amount=float('inf')), record(amount=-1)])
def test_bad_binary(raw):
    with pytest.raises(ValueError):
        m.parse_day_bytes(raw)


def test_strict_prior_means_and_warmup():
    r = m.build_daily(rows())
    assert r[19]['past20_mean_yuan'] is None
    assert r[20]['past20_mean_yuan'] == 10.5e8
    assert r[20]['ratio20'] == 21/10.5
    assert r[59]['ratio60'] is None
    assert r[60]['past60_mean_yuan'] == 30.5e8
    changed=rows()
    changed[60]['amount_yuan']=1e20
    z=m.build_daily(changed)
    assert z[60]['past60_mean_yuan']==r[60]['past60_mean_yuan']


def test_future_prefix_invariant():
    original=m.build_daily(rows(70))
    assert m.build_daily(rows(90))[:70] == original
    future=rows(90)
    future[70]['amount_yuan']=1e30
    assert m.build_daily(future)[:70] == original


def test_missing_window_not_partial_average():
    r=rows()
    r[7]['amount_yuan']=None
    out=m.build_daily(r)
    assert out[20]['ratio20'] is None
    assert out[28]['ratio20'] is not None
    assert out[60]['ratio60'] is None
    assert out[68]['ratio60'] is not None
    assert out[7]['amount_yi'] is None


def test_april_thursday_month_end_and_no_future_price():
    ds=['2026-04-01','2026-04-10','2026-04-20','2026-04-30']
    p=prices(['2026-03-31']+ds)
    out=m.build_monthly(daily_dates(ds),axes(ds),p)[0]
    assert out['month_complete']
    assert out['index_status']=='OK'
    assert out['index_return']==pytest.approx(.04)
    assert out['eq_ret_compound']==pytest.approx(1.01**4-1)
    p+=prices(['2026-05-01','2026-12-31'])
    assert m.build_monthly(daily_dates(ds),axes(ds),p)[0]==out


def test_october_tail_incomplete_despite_price_future():
    ds=['2026-10-20','2026-10-29']
    out=m.build_monthly(daily_dates(ds),axes(ds),prices(['2026-10-19']+ds+['2026-10-30']))[0]
    assert not out['month_complete']
    assert out['index_return'] is None
    assert out['index_status']=='INCOMPLETE_MONTH'


@pytest.mark.parametrize('pdays', [
    ['2026-04-01','2026-04-10','2026-04-20','2026-04-30'], # missing previous
    ['2026-03-31','2026-04-01','2026-04-20','2026-04-30'], # missing within month
    ['2026-03-31','2026-04-01','2026-04-10','2026-04-20'], # missing last
    ['2026-03-01','2026-04-01','2026-04-10','2026-04-20','2026-04-30'], # stale previous
])
def test_missing_price_or_long_gap_rejected(pdays):
    ds=['2026-04-01','2026-04-10','2026-04-20','2026-04-30']
    assert m.build_monthly(daily_dates(ds),axes(ds),prices(pdays))[0]['index_return'] is None


def test_internal_gap_reject_even_matching_boundaries():
    ds=['2026-04-01','2026-04-30']
    out=m.build_monthly(daily_dates(ds),axes(ds),prices(['2026-03-31']+ds))[0]
    assert out['index_status']=='INVALID_CLOSE_OR_GAP_GT14'


def test_axes_missing_day_explicit_no_compound():
    ds=['2026-04-01','2026-04-10','2026-04-20','2026-04-30']
    out=m.build_monthly(daily_dates(ds),axes(ds[:-1]),[])[0]
    assert out['days']==4 and out['axes_days']==3
    assert out['breadth_days']==3
    assert not out['axes_complete']
    assert out['eq_ret_compound'] is None
    assert out['breadth_mean']==.5


def test_next_month_proves_previous_month_closed_no_calendar_needed():
    ds=['2026-02-27','2026-03-02']
    out=m.build_monthly(daily_dates(ds),axes(ds),[])
    assert out[0]['month_complete']
    assert not out[1]['month_complete']


def test_no_weekly_flow_features_or_monthly_doublecount():
    r=m.build_daily(rows())
    assert all('m_fin_flow_w' not in d and 'ax_breadth' not in d for d in r)
    out=m.build_monthly(r,[],[])
    assert all('m_fin_flow_w' not in d and 'l1_fam_delta_w' not in d for d in out)


def test_duplicate_sources_fail():
    ds=['2026-04-30']
    with pytest.raises(ValueError):
        m.build_monthly(daily_dates(ds),axes(ds)*2,[])
    with pytest.raises(ValueError):
        m.build_monthly(daily_dates(ds),[],prices(ds)*2)


def test_trailing_gap_including_current_boundary_rejected():
    r=rows(90)
    for x in r[65:]:
        x['date']=(date.fromisoformat(x['date'])+timedelta(days=30)).isoformat()
    out=m.build_daily(r)
    assert out[64]['ratio20'] is not None
    assert out[65]['past20_mean_yuan'] is None
    assert out[65]['past20_status']=='GAP_GT14'
    assert out[84]['ratio20'] is None
    assert out[85]['ratio20'] is not None
    assert out[89]['ratio60'] is None
    assert out[0]['available_at']=='2024-01-02T00:00:00+08:00'
