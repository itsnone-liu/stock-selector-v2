import csv
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2c_diffusion_outcomes.py'
spec = importlib.util.spec_from_file_location('diffusion_outcomes', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def entry(at='2024-01-30T18:00:00+08:00'):
    return dict(episode_id='D001', arm='DIFFUSION', stage='ENTRY', week='2024-W05',
                assessment_at=at, index_close='100', reason='fixture')


def fixture(end=date(2025, 2, 5)):
    start = date(2024, 1, 29)
    bars = []
    while start <= end:
        if start.weekday() < 5:
            bars.append(dict(trade_date=start.isoformat(), open=100, close=102, low=95, high=105))
        start += timedelta(days=1)
    return bars, [dict(date=b['trade_date']) for b in bars]


class DiffusionOutcomesTest(unittest.TestCase):
    def evaluate(self, bars=None, tdx=None, at=None, horizons=(3, 6, 12)):
        if bars is None:
            bars, tdx = fixture()
        return m.build([entry(at) if at else entry()], bars, tdx, horizons)

    def assert_blank(self, row):
        for key in ('return', 'MAE', 'MFE', 'first_10pct_days', 'hit_10pct', 'observed_days'):
            self.assertEqual(row[key], '', key)

    def test_month_clamp(self):
        self.assertEqual(m.addmonth(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(m.addmonth(date(2023, 1, 31), 1), date(2023, 2, 28))
        self.assertEqual(m.addmonth(date(2024, 2, 29), 12), date(2025, 2, 28))
        rows = self.evaluate()
        self.assertEqual([r['target_date'] for r in rows], ['2024-04-30', '2024-07-31', '2025-01-31'])
        self.assertEqual([r['status'] for r in rows], ['COMPLETE'] * 3)

    def test_strict_future_and_timezone(self):
        for at, expected in [('2024-01-31T09:29:59+08:00', '2024-01-31'),
                             ('2024-01-31T09:30:00+08:00', '2024-02-01'),
                             ('2024-01-31T01:30:00Z', '2024-02-01')]:
            self.assertEqual(self.evaluate(at=at)[0]['entry_date'], expected)
        with self.assertRaises(ValueError):
            self.evaluate(at='2024-01-31T09:30:00')

    def test_right_censored_no_partial_metrics(self):
        bars, tdx = fixture(date(2024, 4, 29))
        for row in self.evaluate(bars, tdx):
            self.assertEqual(row['status'], 'RIGHT_CENSORED')
            self.assert_blank(row)
            self.assertEqual(row['end_date'], '')

    def test_missing_tdx_or_index_day(self):
        bars, tdx = fixture()
        for b, t in [(bars, tdx[:10] + tdx[11:]), (bars[:10] + bars[11:], tdx)]:
            row = self.evaluate(b, t)[0]
            self.assertEqual(row['status'], 'TDX_DATE_MISMATCH')
            self.assert_blank(row)

    def test_path_gap_and_exact_14_day_boundary(self):
        for resume, status in [('2024-02-16', 'COMPLETE'), ('2024-02-19', 'PATH_PRICE_GAP')]:
            bars, _ = fixture()
            bars = [b for b in bars if not ('2024-02-02' < b['trade_date'] < resume)]
            tdx = [dict(date=b['trade_date']) for b in bars]
            row = self.evaluate(bars, tdx)[0]
            self.assertEqual(row['status'], status)
            if status != 'COMPLETE':
                self.assert_blank(row)

    def test_entry_gap_lag_and_no_entry(self):
        bars, tdx = fixture()
        bars = [dict(b) for b in bars if b['trade_date'] >= '2024-02-01']
        bars.insert(0, dict(trade_date='2024-01-16', open=100, close=100, low=99, high=101))
        row = self.evaluate(bars, tdx, at='2024-01-31T18:00:00+08:00')[0]
        self.assertEqual(row['status'], 'ENTRY_PRICE_GAP')
        self.assert_blank(row)
        row = self.evaluate(bars, tdx, at='2024-01-20T00:00:00+08:00')[0]
        self.assertEqual(row['status'], 'ENTRY_LAG')
        row = self.evaluate(at='2026-01-01T00:00:00+08:00')[0]
        self.assertEqual(row['status'], 'NO_ENTRY')
        self.assert_blank(row)

    def test_mae_mfe_and_wait(self):
        bars, tdx = fixture()
        for b in bars:
            if b['trade_date'] == '2024-01-31':
                b.update(low=80, high=125, close=110)
        row = self.evaluate(bars, tdx)[0]
        self.assertAlmostEqual(row['MAE'], -.20)
        self.assertAlmostEqual(row['MFE'], .25)
        self.assertAlmostEqual(row['return'], .02)
        self.assertEqual(row['first_10pct_days'], 1)
        self.assertEqual(row['hit_10pct'], 1)
        for b in bars:
            b.update(low=100, high=105, close=102)
        row = self.evaluate(bars, tdx)[0]
        self.assertEqual(row['MAE'], 0)
        self.assertEqual(row['first_10pct_days'], '')
        self.assertEqual(row['hit_10pct'], 0)
        for b in bars:
            b.update(low=90, high=100, close=99)
        self.assertEqual(self.evaluate(bars, tdx)[0]['MFE'], 0)

    def test_wait_counts_observations_not_calendar_days(self):
        bars, tdx = fixture()
        next(b for b in bars if b['trade_date'] == '2024-02-05').update(close=110, high=111)
        row = self.evaluate(bars, tdx)[0]
        self.assertEqual(row['first_10pct_days'], 4)

    def test_partial_endpoint_and_lag(self):
        # A Sunday target uses Friday, without requiring a complete ISO week.
        row = self.evaluate(at='2024-02-01T18:00:00+08:00')[0]
        self.assertEqual(row['target_date'], '2024-05-02')
        self.assertEqual(row['end_date'], '2024-05-02')
        bars, tdx = fixture()
        row = self.evaluate(bars, tdx, at='2024-01-31T18:00:00+08:00', horizons=(7,))[0]
        self.assertEqual(row['target_date'], '2024-09-01')
        self.assertEqual(row['end_date'], '2024-08-30')
        self.assertEqual(row['status'], 'COMPLETE')
        bars = [b for b in bars if not ('2024-04-22' <= b['trade_date'] <= '2024-04-30')]
        row = self.evaluate(bars, tdx)[0]
        self.assertEqual(row['status'], 'ENDPOINT_LAG')
        self.assert_blank(row)

    def test_invalid_bar_is_not_skipped(self):
        bars, tdx = fixture()
        next(b for b in bars if b['trade_date'] == '2024-01-31')['open'] = 0
        row = self.evaluate(bars, tdx)[0]
        self.assertEqual(row['entry_date'], '2024-01-31')
        self.assertEqual(row['status'], 'INVALID_PRICE')
        self.assert_blank(row)

    def test_empty_entries_cli_has_header(self):
        self.assertEqual(m.build([], [], []), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'entries.csv').write_text('episode_id,arm,stage,week,assessment_at,index_close,reason\n')
            (root / 'index.json').write_text(json.dumps({'rows': []}))
            (root / 'tdx.csv').write_text('date\n')
            subprocess.run([sys.executable, str(SCRIPT), '--entries', str(root / 'entries.csv'),
                            '--index', str(root / 'index.json'), '--tdx', str(root / 'tdx.csv'),
                            '--out', str(root / 'out.csv')], check=True, capture_output=True)
            with (root / 'out.csv').open() as stream:
                self.assertEqual(list(csv.reader(stream)), [m.FIELDS])


if __name__ == '__main__':
    unittest.main()
