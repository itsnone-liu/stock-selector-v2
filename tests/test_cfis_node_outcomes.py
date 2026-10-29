import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2b_node_outcomes.py'
spec = importlib.util.spec_from_file_location('node_outcomes', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(n=14):
    start = date(2024, 1, 8)
    weeks, bars = [], []
    for i in range(n):
        mon = start + timedelta(weeks=i)
        weeks.append({'week': m.week_id(mon), 'week_end': (mon + timedelta(days=4)).strftime('%Y%m%d')})
        for j in range(5):
            bars.append({'trade_date': (mon + timedelta(days=j)).isoformat(),
                         'open': 100, 'low': 95, 'high': 110, 'close': 102})
    return weeks, bars


def node(at='2024-01-05T18:00:00+08:00'):
    return {'episode_id': 'ep1', 'stage': 'A', 'week': '2024-W01',
            'assessment_at': at, 'anchor_low': '95', 'index_close': '100',
            'feature_reason': 'test', 'known_event_ids': ''}


class NodeOutcomesTest(unittest.TestCase):
    def evaluate(self, at='2024-01-05T18:00:00+08:00', n=14):
        w, b = fixture(n)
        return m.build([node(at)], w, b)

    def assert_empty_metrics(self, r):
        for k in ('return', 'MAE', 'MFE', 'first_5pct_days', 'hit_5pct', 'observed_days'):
            self.assertEqual(r[k], '', k)

    def test_friday_assessment_never_precedes_next_week(self):
        rows = self.evaluate()
        for h, r in zip((4, 8, 12), rows):
            self.assertEqual(r['entry_date'], '2024-01-08')
            self.assertEqual(r['window_start_week'], '2024-W02')
            self.assertEqual(r['window_end_week'], f'2024-W{h+1:02d}')
            self.assertEqual(len(r['window_weeks'].split(';')), h)
            self.assertEqual(r['status'], 'COMPLETE')
            self.assertAlmostEqual(r['return'], .02)
            self.assertAlmostEqual(r['MAE'], -.05)
            self.assertAlmostEqual(r['MFE'], .10)
            self.assertEqual(r['hit_5pct'], 0)
            self.assertEqual(r['first_5pct_days'], '')
            self.assertEqual(r['wait_status'], 'NOT_REACHED_RIGHT_CENSORED')

    def test_wait_uses_close_and_entry_day_one(self):
        w, b = fixture()
        b[0]['close'] = 105
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['first_5pct_days'], 1)
        self.assertEqual(r['hit_5pct'], 1)
        b[0]['close'] = 102
        b[5]['close'] = 106
        self.assertEqual(m.build([node()], w, b)[0]['first_5pct_days'], 6)
        b[5]['close'] = 102
        b[20]['close'] = 106
        r4, r8, _ = m.build([node()], w, b)
        self.assertEqual(r4['hit_5pct'], 0)
        self.assertEqual(r8['first_5pct_days'], 21)

    def test_entry_intraday_and_midweek_not_rolled(self):
        for at in ('2024-01-08T09:30:00+08:00',
                   '2024-01-10T18:00:00+08:00'):
            r = self.evaluate(at)[0]
            self.assertEqual(r['status'], 'INCOMPLETE_ENTRY_WEEK')
            self.assert_empty_metrics(r)
        self.assertEqual(self.evaluate('2024-01-08T00:00:00+08:00')[0]['status'], 'COMPLETE')
        # Sunday UTC == Monday before the Shanghai open, no false UTC entry day.
        self.assertEqual(self.evaluate('2024-01-07T16:00:00Z')[0]['entry_date'], '2024-01-08')

    def test_future_assessment(self):
        r = self.evaluate('2030-01-01T00:00:00+08:00')[0]
        self.assertEqual(r['status'], 'RIGHT_CENSORED_NO_ENTRY')
        self.assertEqual(r['entry_date'], '')
        self.assert_empty_metrics(r)

    def test_entry_more_than_seven_days(self):
        r = self.evaluate('2023-12-30T18:00:00+08:00')[0]
        self.assertEqual(r['status'], 'ENTRY_GAP')
        self.assert_empty_metrics(r)

    def test_entry_does_not_cross_historical_gap_even_near_assessment(self):
        w, b = fixture()
        b.insert(0, {'trade_date': '2023-12-01', 'open': 100, 'high': 110, 'low': 95, 'close': 102})
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'ENTRY_GAP')
        self.assert_empty_metrics(r)

    def test_right_censor_no_partial_metrics(self):
        r4, r8, r12 = self.evaluate(n=5)
        self.assertEqual(r4['status'], 'COMPLETE')
        self.assertEqual(r8['status'], 'RIGHT_CENSORED_WEEKLY')
        self.assert_empty_metrics(r8)
        self.assert_empty_metrics(r12)

    def test_missing_daily_endpoint(self):
        w, b = fixture()
        del b[9]
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'MISSING_ENDPOINT')
        self.assert_empty_metrics(r)

    def test_missing_weekly_row_not_silently_skipped(self):
        w, b = fixture()
        del w[1]
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'MISSING_WEEKLY')
        self.assert_empty_metrics(r)

    def test_daily_gap_and_natural_holiday_week(self):
        w, b = fixture()
        # Missing 3 calendar weeks must never count as continuous observations.
        missing = set(x['week'] for x in w[1:4])
        w = [x for x in w if x['week'] not in missing]
        b = [x for x in b if m.week_id(m.as_date(x['trade_date'])) not in missing]
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'WEEKLY_GAP')
        self.assert_empty_metrics(r)
        # One natural fully closed week is not manufactured into an observation.
        w, b = fixture()
        missing = w.pop(1)['week']
        b = [x for x in b if m.week_id(m.as_date(x['trade_date'])) != missing]
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'COMPLETE')
        self.assertEqual(r['window_end_week'], '2024-W06')
        self.assertNotIn(missing, r['window_weeks'])

    def test_thursday_cutoff_needs_later_confirmation(self):
        w, b = fixture(4)
        w[-1]['week_end'] = '20240201'  # Thursday
        b = b[:-1]
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['status'], 'RIGHT_CENSORED_PARTIAL_WEEK')
        self.assert_empty_metrics(r)
        b.append({'trade_date': '2024-02-05', 'open': 100, 'low': 95, 'high': 110, 'close': 102})
        self.assertEqual(m.build([node()], w, b)[0]['status'], 'COMPLETE')

    def test_ohlc_path_not_weekly_close_proxy_and_zero_baseline(self):
        w, b = fixture()
        b[7]['low'], b[8]['high'] = 80, 130
        r = m.build([node()], w, b)[0]
        self.assertAlmostEqual(r['MAE'], -.2)
        self.assertAlmostEqual(r['MFE'], .3)
        for bar in b:
            bar.update(open=105, low=104, high=110, close=106)
        b[0]['open'], b[0]['low'] = 100, 100
        r = m.build([node()], w, b)[0]
        self.assertEqual(r['MAE'], 0)

    def test_invalid_duplicate_rejected(self):
        w, b = fixture()
        with self.assertRaises(ValueError):
            m.build([node()], w, b + [b[0]])
        with self.assertRaises(ValueError):
            m.build([node()], w + [w[0]], b)

    def test_empty_nodes_output_header_and_no_node_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes, weekly, index, out = [root / n for n in ('nodes.csv', 'weekly.csv', 'index.json', 'out.csv')]
            header = ','.join(node()) + '\n'
            nodes.write_text(header)
            w, b = fixture()
            with weekly.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['week', 'week_end'])
                writer.writeheader()
                writer.writerows(w)
            index.write_text(json.dumps({'rows': b}))
            subprocess.run([sys.executable, str(SCRIPT), '--nodes', str(nodes),
                            '--weekly', str(weekly), '--index', str(index), '--out', str(out)],
                           check=True, capture_output=True, text=True)
            self.assertEqual(out.read_text().strip(), ','.join(m.FIELDS))
            self.assertEqual(nodes.read_text(), header)


if __name__ == '__main__':
    unittest.main()
