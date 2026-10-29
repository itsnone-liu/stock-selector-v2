import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('episode_audit', ROOT / 'scripts/cfis/is2b_episode_audit.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def feature(i, **overrides):
    end = date(2024, 1, 5) + timedelta(weeks=i)
    f = dict(week=m.candidate.week_key(end), week_end=end.strftime('%Y%m%d'),
             assessment_at=(end + timedelta(days=3)).isoformat() + 'T00:00:00+08:00',
             index_close=100, index_low=95, index_week_return=.01,
             coverage_status='COMPLETE', current_known=True, a_candidate=False,
             ax_breadth=.6, ax_part=1.1, feature_reason='COMPLETE', dd12=-.1)
    f.update(overrides)
    return f


def fixture(n=15):
    return [feature(i, a_candidate=(i == 0)) for i in range(n)]


class EpisodeAuditTests(unittest.TestCase):
    def test_frozen_alignment(self):
        features_path = ROOT / 'data/cfis/is2b_features.csv'
        nodes_path = ROOT / 'data/cfis/is2b_nodes.csv'
        if not features_path.exists() or not nodes_path.exists():
            self.skipTest('ignored frozen data not available')
        features, nodes = m.read_csv(features_path), m.read_csv(nodes_path)
        trace, summaries = m.audit(features, nodes)
        self.assertEqual(len(trace), len(features))
        self.assertEqual(sum(bool(t['upgrade']) for t in trace), len(nodes))
        self.assertEqual(len(summaries), len({n['episode_id'] for n in nodes}))

    def test_alignment_raises_on_frozen_dates_episode_stage_or_count(self):
        features = fixture(4)
        nodes = m.candidate.build_nodes(features)
        m.audit(features, nodes)
        for key in m.ALIGN_FIELDS:
            bad = [dict(n) for n in nodes]
            bad[0][key] = 'WRONG'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'frozen node mismatch'):
                m.audit(features, bad)
        with self.assertRaises(ValueError):
            m.audit(features, nodes[:-1])

    def test_independent_replay_checked_against_build_nodes(self):
        features = fixture(4)
        original = m.candidate.build_nodes
        try:
            m.candidate.build_nodes = lambda _: []
            with self.assertRaisesRegex(ValueError, 'build_nodes node mismatch'):
                m.audit(features, original(features))
        finally:
            m.candidate.build_nodes = original

    def test_bad_week_ages_never_upgrades_and_breaks_breadth(self):
        features = fixture(6)
        features[1].update(coverage_status='INCOMPLETE')
        features[3].update(current_known='False', index_close=1)
        for i in (4, 5):
            features[i]['index_close'] = 102
        trace, summary = m.audit(features, m.candidate.build_nodes(features))
        self.assertEqual([r['upgrade'] for r in trace], ['A', '', 'B', '', '', 'C'])
        self.assertEqual(trace[1]['age'], 1)
        self.assertEqual(trace[3]['age'], 3)
        self.assertEqual(trace[3]['index_close'], '')
        self.assertEqual(trace[3]['termination'], '')
        self.assertEqual(summary[0]['wait_C_weeks'], 5)

    def test_loss_on_incomplete_known_week_and_loss_before_expiry(self):
        features = fixture(14)
        for i in range(1, 12):
            features[i].update(coverage_status='INCOMPLETE')
        features[12].update(index_close=90, coverage_status='INCOMPLETE', a_candidate=True)
        features[13]['a_candidate'] = True
        trace, summaries = m.audit(features, m.candidate.build_nodes(features))
        self.assertEqual(trace[12]['termination'], 'LOSS')
        self.assertEqual(trace[12]['upgrade'], '')
        self.assertEqual(trace[12]['age'], 12)
        self.assertEqual(trace[12]['state'], 'NONE')
        self.assertEqual(summaries[0]['terminate_close'], 90)
        self.assertEqual(trace[13]['upgrade'], 'A')

    def test_expiry_consumes_week_no_reA_or_upgrade_and_postexpiry_not_recovery(self):
        features = fixture(15)
        for f in features[1:]:
            f['ax_part'] = .5
        features[12].update(a_candidate=True, ax_part=1.2, index_close=110)
        features[13].update(ax_part=1.2, index_close=120)
        trace, summaries = m.audit(features, m.candidate.build_nodes(features))
        self.assertEqual(trace[12]['termination'], 'EXPIRED')
        self.assertEqual(trace[12]['upgrade'], '')
        self.assertEqual(trace[13]['episode_id'], '')
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]['B_week'], '')
        self.assertEqual(summaries[0]['wait_B_status'], 'TERMINATED_UNREACHED')
        self.assertEqual(summaries[0]['observed_age'], 12)
        self.assertEqual(summaries[0]['last_observed_week'], features[12]['week'])

    def test_same_week_cannot_cross_stages_and_C_remains_active(self):
        features = fixture(14)
        for f in features:
            f['index_close'] = 101
        features[2]['index_close'] = 102
        trace, _ = m.audit(features, m.candidate.build_nodes(features))
        self.assertEqual([t['upgrade'] for t in trace[:3]], ['A', 'B', 'C'])
        self.assertEqual(trace[11]['state'], 'C')
        self.assertEqual(trace[12]['termination'], 'EXPIRED')

    def test_right_censoring_and_at_A_snapshot(self):
        features = fixture(3)
        features[1].update(ax_part=.5, dd12=-.3)
        features[2].update(ax_part=.5)
        trace, summaries = m.audit(features, m.candidate.build_nodes(features))
        s = summaries[0]
        self.assertTrue(s['right_censored'])
        self.assertEqual(s['terminate_status'], 'RIGHT_CENSORED')
        self.assertEqual(s['terminate_week'], '')
        self.assertEqual(s['terminate_close'], '')
        self.assertEqual(s['wait_B_weeks'], '')
        self.assertEqual(s['wait_B_observed_weeks'], 2)
        self.assertEqual(s['wait_C_status'], 'RIGHT_CENSORED')
        self.assertEqual(s['at_A_dd12'], -.1)
        self.assertEqual(trace[-1]['termination'], '')
        self.assertIn('右删失', m.report_text(trace, summaries))
        self.assertIn('不是策略执行', m.report_text(trace, summaries))

    def test_prefix_trace_invariance_at_every_cut(self):
        features = fixture(30)
        features[4].update(index_close=80)
        features[5].update(a_candidate=True)
        features[8].update(coverage_status='INCOMPLETE')
        features[18].update(a_candidate=True)
        full, _ = m.audit(features, m.candidate.build_nodes(features))
        for n in range(len(features) + 1):
            prefix = features[:n]
            trace, _ = m.audit(prefix, m.candidate.build_nodes(prefix))
            self.assertEqual(trace, full[:n], f'prefix {n}')

    def test_unknown_week_can_expire_but_not_publish_unknown_price(self):
        features = fixture(13)
        features[-1].update(current_known=False, index_close=1)
        trace, summaries = m.audit(features, m.candidate.build_nodes(features))
        self.assertEqual(trace[-1]['termination'], 'EXPIRED')
        self.assertEqual(summaries[0]['terminate_close'], '')


if __name__ == '__main__':
    unittest.main()
