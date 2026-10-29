"""Focused CF-IS time/return regression tests; no network or large-data rebuild."""
import importlib.util
from pathlib import Path
import sys
import json
import csv
from datetime import date, timedelta

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/cfis' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


is0 = load('is0_weekly_sample')
is1 = load('is1_weekly_atlas')


def rows(n=12):
    start = date(2020, 12, 21)
    return [{'week': is0.iso_week((start + timedelta(weeks=i)).strftime('%Y%m%d')),
             'ax_eq_ret_w': '0.00123456'} for i in range(n)]


@pytest.mark.parametrize('value', ['20240102', '2024-01-02'])
def test_dates(value):
    assert is0.normalize_date(value) == '20240102'


@pytest.mark.parametrize('value', ['20240230', '2024-1-2', '202401020', 'foo'])
def test_invalid_dates(value):
    with pytest.raises(ValueError):
        is0.normalize_date(value)


def test_precision_and_missing():
    assert is0.compound_returns([.0012, .0013]) == pytest.approx(.00250156)
    for values in ([], [None], [.01, None], [float('nan')], [float('inf')]):
        assert is0.compound_returns(values) == ''
    assert is0.compound_returns([0.0]) == 0.0
    assert is1.fnum('nan') is None


def test_complete_forward_only():
    r = rows()
    assert len(is1.fwd_paths(r, [0, 8, 9, 11])) == 1
    assert is1.fwd_paths(r, [0])[0] == pytest.approx((1.00123456 ** 4) - 1)
    r[2]['ax_eq_ret_w'] = ''
    assert is1.fwd_paths(r, [0]) == []
    r[2]['ax_eq_ret_w'] = '0'
    assert len(is1.fwd_paths(r, [0])) == 1


def test_calendar_gaps_and_iso53():
    assert is1._week_gap('2020-W52', '2020-W53') == 1
    assert is1._week_gap('2020-W53', '2021-W01') == 1
    assert is1._week_gap('2020-W52', '2021-W01') == 2
    r = rows(); del r[2]
    assert is1.fwd_paths(r, [0]) == []
    assert is1.rolling_returns(r)[7] is None


def test_eight_full_weeks():
    r = rows()
    values = is1.rolling_returns(r)
    assert values[:7] == [None] * 7
    assert is1.phase(values[0]) == 'INSUFFICIENT8'
    assert values[7] == pytest.approx((1.00123456 ** 8) - 1)
    r[3]['ax_eq_ret_w'] = 'nan'
    assert is1.rolling_returns(r)[7] is None


def test_raw_availability_and_bounds():
    r = {'20240105': {'available_at': '20240105+1 conservative'}}
    result = is0.weekly_timing('2024-W01', [('l1', r)], list(r))
    assert result['assessment_at'] == '2024-01-08T00:00:00+08:00'
    assert result['usable_at'] == result['assessment_at']
    assert json.loads(result['available_at_raw'])['l1'][0]['available_at'] == '20240105+1 conservative'
    assert is0.availability_bound('20240105 evening').isoformat() == '2024-01-05T23:59:59'
    r['20240105']['available_at'] = None
    assert is0.weekly_timing('2024-W01', [('l1', r)], list(r))['usable_at'] == ''


def test_cli_aggregation(tmp_path, monkeypatch):
    dates = ['20240102', '20240103', '20240104', '20240105']
    atoms = {d: {'state': 'OK', 'available_at': d + '+1 conservative'} for d in dates}
    axes = {d: {'eq_ret': .00123456} for d in dates}
    monkeypatch.setattr(is0, 'load_atom_history', lambda *a: (atoms, 0))
    monkeypatch.setattr(is0, 'load_market_axes', lambda *a: (axes, 0))
    monkeypatch.setattr(is0, 'load_episodes', lambda *a: [])
    out = tmp_path / 'out.csv'
    monkeypatch.setattr(sys, 'argv', ['is0', '--start', '2024-01-01', '--end', '2024-01-07', '--out', str(out)])
    is0.main()
    with out.open() as fh:
        row = next(csv.DictReader(fh))
    assert float(row['ax_eq_ret_w']) == pytest.approx(1.00123456 ** 4 - 1)
    axes['20240103']['eq_ret'] = None
    is0.main()
    with out.open() as fh:
        assert next(csv.DictReader(fh))['ax_eq_ret_w'] == ''


def test_cli_bad_range(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['is0', '--start', '2024-02-01', '--end', '20240101'])
    with pytest.raises(SystemExit):
        is0.main()
