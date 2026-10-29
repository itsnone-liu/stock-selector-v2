"""Fixed-rule boundaries, temporal visibility and independent common-sample arms."""
import csv
from datetime import date, datetime, time, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2c_diffusion_entries.py'
spec = importlib.util.spec_from_file_location('is2c_diffusion_entries', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
TZ = timezone(timedelta(hours=8))


def fixture(n=10):
    start = date(2024, 1, 1)
    daily, prices, weeks = [], [], []
    for offset in range(n * 7):
        d = start + timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        daily.append({'date': d.isoformat(), 'amount_yuan': 100,
                      'ratio60': 1.2, 'available_at': m.next_day(d).isoformat()})
        prices.append({'trade_date': d.isoformat(), 'close': 100 + offset})
        if d.weekday() == 4:
            assessment = datetime.combine(d + timedelta(days=3), time(), TZ).isoformat()
            weeks.append({'week': f'{d.isocalendar().year}-W{d.isocalendar().week:02d}',
                          'week_end': d.strftime('%Y%m%d'), 'assessment_at': assessment,
                          'usable_at': assessment, 'availability_unknown': '0',
                          'ax_breadth': .5})
    return weeks, daily, prices


def features(n=10):
    return m.build_features(*fixture(n))


def test_seven_of_ten_inclusive_ratio_boundary():
    w, d, p = fixture(5)
    for r in d[-10:]:
        r['ratio60'] = 1.199999
    for r in d[-7:]:
        r['ratio60'] = 1.2
    r = m.build_features(w, d, p)[-1]
    assert r['amount_count10'] == 7 and r['amount'] is True
    d[-1]['ratio60'] = 1.199999
    r = m.build_features(w, d, p)[-1]
    assert r['amount_count10'] == 6 and r['amount'] is False
    assert r['eligible'] is True


def test_future_prefix_invariant():
    short = fixture(7)
    long = fixture(12)
    assert m.build(*short)[0] == m.build(*long)[0][:7]
    prefix_entries = m.build(*short)[1]
    assert prefix_entries == [r for r in m.build(*long)[1] if r['week'] <= short[0][-1]['week']]
    for r in long[1]:
        if m.day(r['date']) > m.day(short[0][-1]['week_end']):
            r['ratio60'] = 999
    for r in long[2]:
        if m.day(r['trade_date']) > m.day(short[0][-1]['week_end']):
            r['close'] = 1
    assert m.build(*long)[0][:7] == m.build(*short)[0]


def test_no_a_dependency_and_independent_runs():
    # Deliberately minimal weekly rows: no A, margin, state, or event fields.
    f = features()
    f[5]['breadth'] = False
    f[5]['diffusion'] = False
    entries = m.build_entries(f)
    assert len([r for r in entries if r['arm'] == 'DIFFUSION']) == 2
    assert len([r for r in entries if r['arm'] == 'AMOUNT_ONLY']) == 1
    assert len([r for r in entries if r['arm'] == 'PRICE_ONLY']) == 1
    assert all(r['stage'] == r['arm'] for r in entries)
    assert all(list(r) == m.ENTRY_FIELDS for r in entries)


def test_unknown_breaks_runs_and_blocks_next_week():
    w, d, p = fixture()
    w[6]['availability_unknown'] = '1'
    f, entries = m.build(w, d, p)
    assert f[6]['eligible'] is False and f[7]['eligible'] is False
    assert f[6]['amount'] is None and f[7]['breadth'] is None
    assert f[8]['eligible'] is True
    for arm in m.ARMS:
        assert [r['week'] for r in entries if r['arm'] == arm] == [w[4]['week'], w[8]['week']]


def test_common_window_all_arms_require_all_inputs_known():
    w, d, p = fixture()
    w[5]['ax_breadth'] = ''
    f, entries = m.build(w, d, p)
    assert f[5]['amount'] is True and f[5]['price'] is True
    assert not f[5]['eligible'] and not f[6]['eligible']
    baseline = [r['week'] for r in entries if r['arm'] == 'ALL_ELIGIBLE']
    assert baseline == [r['week'] for r in f if r['eligible']]
    assert not ({w[5]['week'], w[6]['week']} & {r['week'] for r in entries})


def test_price_missing_endpoint_not_skipped_and_strict_breakout():
    w, d, p = fixture()
    missing = m.day(w[3]['week_end']).isoformat()
    p = [r for r in p if r['trade_date'] != missing]
    f = m.build_features(w, d, p)
    assert all(not r['price_known'] for r in f[4:8])
    assert f[8]['price_known'] is True
    w, d, p = fixture(5)
    p[-1]['close'] = p[-6]['close']
    f = m.build_features(w, d, p)
    assert f[-1]['price_known'] is True and f[-1]['price'] is False


def test_price_week_endpoint_gap_over_fourteen_days():
    w, d, p = fixture(10)
    # Even five present endpoints cannot bridge a multiweek missing interval.
    w = w[:3] + w[6:]
    f = m.build_features(w, d, p)
    assert not f[4]['price_known']
    assert 'PRICE5_MISSING_INVALID_GAP_OR_NOT_VISIBLE' in f[4]['detail']


def test_tdx_requires_current_week_end_and_all_ten_valid():
    w, d, p = fixture(5)
    d.pop()
    f = m.build_features(w, d, p)
    assert not f[-1]['amount_known'] and not f[-1]['eligible']
    w, d, p = fixture(5)
    d[-7]['ratio60'] = ''
    assert m.build_features(w, d, p)[-1]['amount'] is None
    w, d, p = fixture(5)
    d[-7]['amount_yuan'] = 'nan'
    assert m.build_features(w, d, p)[-1]['amount'] is None


def test_amount_gap_over_fourteen_days():
    w, d, p = fixture(10)
    last = m.day(w[-1]['week_end'])
    d = [r for r in d if not last - timedelta(days=30) <= m.day(r['date']) < last - timedelta(days=3)]
    f = m.build_features(w, d, p)
    assert f[-1]['amount_days'] == 10
    assert f[-1]['amount'] is None


def test_available_time_max_and_no_later_backfill():
    w, d, p = fixture(6)
    end = m.day(w[4]['week_end'])
    w[4]['usable_at'] = m.next_day(end).isoformat()
    f = m.build_features(w, d, p)
    assert f[4]['available_at'] == m.next_day(end).isoformat()
    # Assessments move forward to availability rather than dropping late weeks.
    w[4]['assessment_at'] = datetime.combine(end, time(20), TZ).isoformat()
    w[4]['usable_at'] = w[4]['assessment_at']
    f = m.build_features(w, d, p)
    assert f[4]['eligible']
    assert f[4]['assessment_at'] == m.next_day(end).isoformat()
    w, d, p = fixture(6)
    w[4]['usable_at'] = '2024-03-01T00:00:00+08:00'
    f = m.build_features(w, d, p)
    assert f[4]['eligible']
    assert f[4]['assessment_at'] == w[4]['usable_at']
    assert not f[5]['eligible']  # Previous late weekly input not yet visible.


def test_csv_boolean_roundtrip():
    f = features()
    original = m.build_entries(f)
    text_rows = [{k: str(v) if v is not None else '' for k, v in r.items()} for r in f]
    entries = m.build_entries(text_rows)
    assert [(r['episode_id'], r['week']) for r in original] == [
        (r['episode_id'], r['week']) for r in entries]


def test_empty_outputs_have_header(tmp_path):
    assert m.build([], [], []) == ([], [])
    for name, fields in [('entries', m.ENTRY_FIELDS), ('features', m.FEATURE_FIELDS)]:
        path = tmp_path / f'{name}.csv'
        m.write_csv(path, [], fields)
        with path.open() as f:
            assert next(csv.reader(f)) == fields
            assert list(f) == []


def test_duplicates_rejected():
    w, d, p = fixture()
    with pytest.raises(ValueError, match='duplicate observation week'):
        m.build_features(w + [w[0]], d, p)
    with pytest.raises(ValueError, match='duplicate date'):
        m.build_features(w, d + [d[0]], p)
    with pytest.raises(ValueError, match='duplicate trade_date'):
        m.build_features(w, d, p + [p[0]])
