import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2b_candidate_nodes.py'
spec = importlib.util.spec_from_file_location('candidate_nodes', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(n=30):
    start = date(2024, 1, 1)
    prices = [dict(trade_date='2023-12-29', open=101, high=102, low=99, close=100)]
    weeks = []
    for i in range(n):
        monday = start + timedelta(weeks=i)
        end = monday + timedelta(days=4)
        c = 100 - min(i, 10) * .5
        for j in range(5):
            d = monday + timedelta(days=j)
            prices.append(dict(trade_date=d.isoformat(), open=c, high=c+2, low=c-2, close=c))
        weeks.append(dict(week=m.week_key(end), week_end=end.strftime('%Y%m%d'),
                          days_obs='5', usable_at=(end+timedelta(days=3)).isoformat()+'T00:00:00+08:00',
                          availability_unknown='0', m_fin_flow_w=str(-100+i),
                          l1_fam_delta_w='.01', ax_breadth='.6', ax_part='1.1'))
    return weeks, prices


def feature(i, **overrides):
    end = date(2024, 1, 5) + timedelta(weeks=i)
    f = dict(week=m.week_key(end), week_end=end.strftime('%Y%m%d'),
             assessment_at=(end+timedelta(days=3)).isoformat()+'T00:00:00+08:00',
             index_close=95+i, index_low=90, index_week_return=.01,
             coverage_status='COMPLETE', current_known=True, a_candidate=True,
             ax_breadth=.6, ax_part=1.1, feature_reason='COMPLETE')
    f.update(overrides)
    return f


class FeatureTests(unittest.TestCase):
    def test_prefix_invariance_every_cut(self):
        weeks, prices = fixture()
        full = m.build_features(weeks, prices)
        for n in range(1, len(weeks)+1):
            end = m.day(weeks[n-1]['week_end'])
            past = [p for p in prices if date.fromisoformat(p['trade_date']) <= end]
            self.assertEqual(m.build_features(weeks[:n], past), full[:n])

    def test_future_mutation_cannot_change_history(self):
        weeks, prices = fixture()
        before = m.build_features(weeks, prices)
        cutoff = weeks[15]['week_end']
        for p in prices:
            if date.fromisoformat(p['trade_date']) > m.day(cutoff):
                p.update(close=999, low=1, high=1000)
        for w in weeks[16:]:
            w.update(m_fin_flow_w='99999', availability_unknown='1')
        self.assertEqual(before[:16], m.build_features(weeks, prices)[:16])

    def test_formula_and_window_no_future(self):
        weeks, prices = fixture()
        f = m.build_features(weeks, prices)
        self.assertEqual(f[10]['dd12'], '')
        self.assertAlmostEqual(f[11]['dd12'], 95/100-1)
        self.assertAlmostEqual(f[11]['low_change'], 93/93-1)
        self.assertTrue(f[11]['pressure_easing'])
        self.assertTrue(f[11]['margin_easing'])
        self.assertEqual(f[11]['l1_mean2'], .01)
        self.assertTrue(f[11]['a_candidate'])

    def test_missing_endpoint_not_filled(self):
        weeks, prices = fixture()
        prices = [p for p in prices if p['trade_date'] != '2024-03-22']
        f = m.build_features(weeks, prices)
        self.assertIn('MISSING_ENDPOINT', f[11]['feature_reason'])
        self.assertFalse(f[11]['current_known'])
        self.assertEqual(f[22]['dd12'], '')
        self.assertNotEqual(f[23]['dd12'], '')

    def test_missing_weekly_not_skipped(self):
        weeks, prices = fixture()
        del weeks[10]
        f = m.build_features(weeks, prices)
        self.assertEqual(len(f), 30)
        self.assertIn('MISSING_WEEKLY', f[10]['feature_reason'])
        self.assertEqual(f[21]['dd12'], '')
        self.assertNotEqual(f[22]['dd12'], '')

    def test_unknown_future_and_naive_times_block_windows(self):
        for value in ('', '2025-01-01T00:00:00+08:00', '2024-03-01T00:00:00'):
            weeks, prices = fixture()
            weeks[10]['usable_at'] = value
            f = m.build_features(weeks, prices)
            self.assertEqual(f[11]['dd12'], '')
        weeks, prices = fixture()
        weeks[10]['availability_unknown'] = '1'
        self.assertEqual(m.build_features(weeks, prices)[11]['dd12'], '')

    def test_158_day_gap_blocks_history(self):
        weeks, prices = fixture(40)
        # Keep weekly rows, never bridge a missing index interval.
        lo = date(2024, 2, 2)
        hi = lo + timedelta(days=158)
        prices = [p for p in prices if not lo < date.fromisoformat(p['trade_date']) < hi]
        f = m.build_features(weeks, prices)
        gap_rows = [x for x in f if 'INDEX_GAP' in x['feature_reason']]
        self.assertTrue(gap_rows)
        for x in gap_rows:
            self.assertEqual(x['dd12'], '')
            self.assertFalse(x['a_candidate'])

    def test_negative_day_pressure_not_week_return(self):
        weeks, prices = fixture()
        p = [x for x in prices if '2024-02-26' <= x['trade_date'] <= '2024-03-01'][:5]
        p[1]['close'] = p[0]['close']*.95
        p[1]['low'] = p[1]['close'] - 1
        f = m.build_features(weeks, prices)
        self.assertGreater(f[8]['downside_pressure'], .04)

    def test_missing_margin_or_l1_no_candidate(self):
        for field in ('m_fin_flow_w', 'l1_fam_delta_w'):
            weeks, prices = fixture()
            weeks[11][field] = ''
            f = m.build_features(weeks, prices)
            self.assertFalse(f[11]['a_candidate'])
            self.assertEqual(f[11]['coverage_status'], 'INCOMPLETE')

    def test_partial_current_week_and_invalid_ohlc_block(self):
        weeks, prices = fixture()
        # A Wednesday endpoint is not a finished weekly assessment on Thursday.
        weeks[11]['week_end'] = '20240320'
        weeks[11]['days_obs'] = '3'
        weeks[11]['usable_at'] = '2024-03-21T00:00:00+08:00'
        f = m.build_features(weeks, prices)
        self.assertFalse(f[11]['current_known'])
        self.assertIn('UNKNOWN_TIME', f[11]['feature_reason'])
        weeks, prices = fixture()
        for p in prices:
            if p['trade_date'] == '2024-03-22':
                p['low'] = p['high'] + 1
        self.assertFalse(m.build_features(weeks, prices)[11]['current_known'])

    def test_natural_holiday_week_not_manufactured(self):
        weeks, prices = fixture()
        omitted = weeks.pop(10)['week']
        prices = [p for p in prices if m.week_key(m.day(p['trade_date'])) != omitted]
        f = m.build_features(weeks, prices)
        self.assertEqual(len(f), 29)
        self.assertNotIn(omitted, [x['week'] for x in f])
        self.assertNotEqual(f[11]['dd12'], '')

    def test_duplicate_rejected(self):
        weeks, prices = fixture()
        with self.assertRaises(ValueError):
            m.build_features(weeks, prices + prices[:1])
        with self.assertRaises(ValueError):
            m.build_features(weeks + weeks[:1], prices)


class NodeTests(unittest.TestCase):
    def test_overlapping_a_merges_and_stages_later(self):
        nodes = m.build_nodes([feature(i) for i in range(10)])
        self.assertEqual([x['stage'] for x in nodes], ['A', 'B', 'C'])
        self.assertEqual(len({x['episode_id'] for x in nodes}), 1)
        self.assertEqual([x['week'] for x in nodes], [feature(i)['week'] for i in range(3)])

    def test_loss_priority_over_b_and_c_and_same_week_a(self):
        for when in (1, 2):
            f = [feature(i) for i in range(4)]
            f[when]['index_close'] = 87  # below 90*.97 while upgrade otherwise passes
            nodes = m.build_nodes(f)
            self.assertFalse(any(x['week'] == f[when]['week'] for x in nodes))
            self.assertEqual([x for x in nodes if x['week'] == f[when+1]['week']][0]['stage'], 'A')

    def test_a_week_cannot_fail_itself(self):
        nodes = m.build_nodes([feature(0, index_low=100, index_close=95)])
        self.assertEqual([x['stage'] for x in nodes], ['A'])

    def test_unknown_blocks_upgrade_not_restart_or_pause_age(self):
        f = [feature(i, coverage_status='INCOMPLETE', current_known=False) for i in range(15)]
        f[0] = feature(0)
        f[13] = feature(13)
        nodes = m.build_nodes(f)
        self.assertEqual([x['stage'] for x in nodes], ['A', 'A'])
        self.assertNotEqual(nodes[0]['episode_id'], nodes[1]['episode_id'])

    def test_c_requires_consecutive_breadth_and_later_than_b(self):
        f = [feature(0), feature(1), feature(2, ax_breadth=.4), feature(3), feature(4)]
        nodes = m.build_nodes(f)
        self.assertEqual(nodes[-1]['week'], f[4]['week'])
        self.assertEqual(nodes[-1]['stage'], 'C')

    def test_expiry_has_priority_and_never_upgrades_week12(self):
        f = [feature(i, ax_part=.5) for i in range(14)]
        f[12]['ax_part'] = 1.1
        nodes = m.build_nodes(f)
        self.assertEqual([x['stage'] for x in nodes], ['A', 'A'])
        self.assertEqual(nodes[-1]['week'], f[13]['week'])

    def test_events_past_28d_only_and_inclusive_boundaries(self):
        f = feature(0)
        t = m.timestamp(f['assessment_at'])
        events = dict(events=[dict(event_id=k, first_usable_at=(t+timedelta(days=d)).isoformat())
                             for k, d in [('old', -29), ('boundary', -28), ('now', 0), ('future', 1)]])
        nodes = m.build_nodes([f], events)
        self.assertEqual(json.loads(nodes[0]['known_event_ids']), ['boundary', 'now'])

    def test_node_prefix_and_future_event_invariance(self):
        f = [feature(i) for i in range(18)]
        full = m.build_nodes(f)
        for n in range(1, 19):
            self.assertEqual(m.build_nodes(f[:n]), [x for x in full if x['week'] <= f[n-1]['week']])
        events = [dict(event_id='future', first_usable_at='2030-01-01T00:00:00+08:00')]
        self.assertEqual(full, m.build_nodes(f, events))

    def test_empty_nodes_still_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nodes.csv'
            m.write_csv(path, [], m.NODE_FIELDS)
            self.assertEqual(path.read_text().strip(), ','.join(m.NODE_FIELDS))


if __name__ == '__main__':
    unittest.main()
