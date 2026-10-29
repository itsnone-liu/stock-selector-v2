import copy
import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2b_coverage_diagnostic.py'
spec = importlib.util.spec_from_file_location('coverage_diagnostic', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def feature(week='2024-W01', **kwargs):
    row = dict(week=week, week_end='20240105', assessment_at='2024-01-05T18:00:00+08:00',
               current_known=True, coverage_status='COMPLETE', feature_reason='COMPLETE',
               a_candidate=False, dd12=-.06, low_change=0, pressure_easing=True,
               margin_easing=True, l1_mean2=0, index_close=100, index_low=95)
    row.update(kwargs)
    return row


def fixture(n=6, close=105):
    weeks, bars = [], []
    for i in range(n):
        mon = date(2024, 1, 8) + timedelta(weeks=i)
        weeks.append(dict(week=m.outcomes.week_id(mon), week_end=(mon + timedelta(days=4)).strftime('%Y%m%d')))
        for j in range(5):
            bars.append(dict(trade_date=(mon + timedelta(days=j)).isoformat(), open=100,
                             low=95, high=max(110, close), close=close))
    return weeks, bars


def node(week='2024-W01', stage='A', **kwargs):
    row = dict(week=week, stage=stage, episode_id='ep1', anchor_low=95,
               assessment_at='2024-01-05T18:00:00+08:00')
    row.update(kwargs)
    return row


class CoverageDiagnosticTest(unittest.TestCase):
    def test_boundary_and_strict_outcome_inheritance(self):
        weeks, bars = fixture()
        rows = m.build([feature()], [], weeks, bars)
        synthetic = dict(episode_id='COVERAGE-2024-W01', stage='SYNTHETIC',
                         week='2024-W01', assessment_at=feature()['assessment_at'])
        expected = m.outcomes.build([synthetic], weeks, bars, horizons=(4,))[0]
        for key in m.outcomes.FIELDS:
            self.assertEqual(rows[0][key], expected[key])
        self.assertTrue(rows[0]['rally_4w'])
        self.assertAlmostEqual(rows[0]['return'], .05)
        weeks, bars = fixture(close=104.999)
        self.assertFalse(m.build([feature()], [], weeks, bars)[0]['rally_4w'])

    def test_missing_and_right_censored_never_false(self):
        weeks, bars = fixture(n=2)
        row = m.build([feature()], [], weeks, bars)[0]
        self.assertNotEqual(row['status'], 'COMPLETE')
        self.assertEqual(row['rally_4w'], '')
        self.assertEqual(row['return'], '')
        weeks, bars = fixture()
        weeks.pop(1)
        row = m.build([feature()], [], weeks, bars)[0]
        self.assertEqual(row['status'], 'MISSING_WEEKLY')
        self.assertEqual(row['rally_4w'], '')
        self.assertEqual(m.build([feature(current_known=False)], [], weeks, bars), [])

    def test_classification_actual_merged_incomplete_failed(self):
        weeks, bars = fixture()
        features = [feature('2024-W01', a_candidate=True),
                    feature('2024-W02', a_candidate=True),
                    feature('2024-W03', coverage_status='INCOMPLETE', dd12='', pressure_easing=False),
                    feature('2024-W04', dd12=-.01, low_change=-.02, margin_easing=False),
                    feature('2024-W05', pressure_easing='')]
        rows = m.build(features, [node()], weeks, bars)
        self.assertEqual([r['category'] for r in rows], [*m.CATEGORIES, 'feature_incomplete'])
        self.assertEqual(rows[2]['dd12_deep'], 'unknown')
        self.assertEqual(rows[2]['failed_conditions'], '')
        self.assertEqual(rows[3]['failed_conditions'], 'dd12_deep;low_stable;margin_easing')
        self.assertEqual(rows[4]['unknown_conditions'], 'pressure_easing')
        self.assertNotEqual(rows[4]['pressure_easing'], False)
        self.assertEqual(rows[1]['active_episode_status'], 'active')
        self.assertIn('不是规则召回率', m.report(rows))

    def test_runs_use_original_observation_indices_not_compressed_rows(self):
        rows = [dict(observation_index=i, rally_4w=v) for i, v in
                [(0, True), (1, True), (2, ''), (3, True), (5, True), (6, False), (7, True)]]
        self.assertEqual(m.rally_runs(rows), 4)
        self.assertEqual(m.rally_runs([]), 0)

    def test_future_label_cannot_change_diagnostic_inputs(self):
        features, nodes = [feature(dd12=-.01)], []
        before = copy.deepcopy(features)
        weeks, bars = fixture(close=105)
        a = m.build(features, nodes, weeks, bars)[0]
        _, other_bars = fixture(close=100)
        b = m.build(features, nodes, weeks, other_bars)[0]
        self.assertNotEqual(a['rally_4w'], b['rally_4w'])
        for key in ['category', 'failed_conditions', 'unknown_conditions', *m.CONDITIONS,
                    'active_episode_status', 'active_episode_id', 'active_episode_stage']:
            self.assertEqual(a[key], b[key])
        self.assertEqual(features, before)

    def test_active_loss_expiry_c_and_unknown(self):
        features = [feature(f'2024-W{i+1:02d}') for i in range(14)]
        nodes = [node(), node('2024-W02', stage='B'), node('2024-W03', stage='C')]
        states = m.replay_active(features, nodes)
        self.assertEqual(states[2]['active_episode_stage'], 'C')
        self.assertEqual(states[11]['active_episode_status'], 'active')
        self.assertEqual(states[12]['active_episode_status'], 'none')
        self.assertEqual(states[12]['episode_exit_reason'], 'EXPIRED_12')
        features[1]['index_close'] = 95 * .97
        self.assertEqual(m.replay_active(features, nodes)[1]['active_episode_status'], 'active')
        features[1]['index_close'] = 95 * .97 - .001
        self.assertEqual(m.replay_active(features, nodes)[1]['episode_exit_reason'], 'ANCHOR_LOSS')
        features[1]['index_close'] = ''
        self.assertEqual(m.replay_active(features, nodes)[1]['active_episode_status'], 'unknown')
        self.assertEqual(m.replay_active(features, nodes)[12]['active_episode_status'], 'none')
        features[1]['current_known'] = False
        self.assertEqual(m.replay_active(features, nodes)[1]['active_episode_status'], 'unknown')
        self.assertEqual(m.replay_active(features, nodes)[2]['active_episode_status'], 'unknown')
        features[12]['index_close'] = 1
        self.assertEqual(m.replay_active(features, nodes)[12]['episode_exit_reason'], 'ANCHOR_LOSS')

    def test_future_nodes_not_used_at_earlier_assessment(self):
        rows = m.replay_active([feature()], [node(assessment_at='2024-01-06T18:00:00+08:00')])
        self.assertEqual(rows[0]['active_episode_status'], 'none')


if __name__ == '__main__':
    unittest.main()
