"""stdlib fixtures; run with pytest --noconftest."""
import importlib.util
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('timeline', Path(__file__).resolve().parents[1] / 'scripts/cfis/is2b_event_timeline.py')
timeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timeline)


def event(eid='a', at='2024-01-10T12:00:00+08:00', cluster='cluster'):
    return dict(event_id=eid, first_usable_at=at, event_cluster_id=cluster)


def week(n, **changes):
    monday = date.fromisocalendar(2024, n, 1)
    row = dict(week=f'2024-W{n:02}', days_obs='5', ax_days='5', ax_eq_ret_w='0.1',
               usable_at=(monday + timedelta(days=7)).isoformat() + 'T00:00:00+08:00',
               availability_unknown='0', **{m: '2' for m in timeline.METRICS})
    row.update(changes)
    return row


class TimelineTests(unittest.TestCase):
    def build(self, weeks=None, events=None, baseline=()):
        return timeline.build_timeline(events or [event()], weeks if weeks is not None else [week(n) for n in range(1, 7)], baseline)

    def test_future_cluster_members_never_visible_and_all_events_retained(self):
        rows = self.build(events=[event('future', '2024-01-11T12:00:00+08:00'), event(),
                                 event('same', '2024-01-10T12:00:00+08:00')])
        self.assertEqual([r['event_id'] for r in rows], ['a', 'same', 'future'])
        self.assertEqual(json.loads(rows[0]['visible_cluster_ids']), ['a', 'same'])
        self.assertEqual(json.loads(rows[2]['visible_cluster_ids']), ['a', 'same', 'future'])

    def test_event_week_excluded_all_horizons_and_compounding(self):
        row = self.build()[0]
        self.assertEqual(row['event_week'], '2024-W02')
        self.assertEqual(row['post4_weeks'], '2024-W03|2024-W04|2024-W05|2024-W06')
        self.assertAlmostEqual(row['post4_ew_compound_proxy'], 1.1 ** 4 - 1)
        self.assertEqual(row['post1_weeks'], '2024-W03')
        self.assertEqual(row['post2_weeks'], '2024-W03|2024-W04')

    def test_pre_strict_time_unknown_and_21_day_boundary(self):
        at = '2024-02-01T12:00:00+08:00'
        cases = [week(1, usable_at='2024-01-11T12:00:00+08:00'),
                 week(2, usable_at=at),
                 week(3, usable_at='2024-01-31T12:00:00+08:00', availability_unknown='1')]
        row = self.build(cases, [event(at=at)])[0]
        self.assertEqual(row['pre_week'], '2024-W01')
        self.assertEqual(row['pre_l1_fam_delta_w'], '2')
        cases[0]['usable_at'] = '2024-01-11T11:59:59+08:00'
        self.assertEqual(self.build(cases, [event(at=at)])[0]['pre_week'], '')

    def test_pre_selected_by_availability_not_week(self):
        row = self.build([week(1, usable_at='2024-01-10T11:00:00+08:00'),
                          week(2, usable_at='2024-01-10T10:00:00+08:00')])[0]
        self.assertEqual(row['pre_week'], '2024-W01')

    def test_post_missing_never_zero_or_skip_bad_week(self):
        for changes in ({'ax_days': '0'}, {'ax_eq_ret_w': ''}, {'ax_eq_ret_w': 'nan'}, {'usable_at': 'invalid'}):
            with self.subTest(changes=changes):
                weeks = [week(n, **(changes if n == 3 else {})) for n in range(1, 8)]
                row = self.build(weeks)[0]
                self.assertEqual(row['post1_status'], 'MISSING_INVALID_WEEK')
                self.assertEqual(row['post4_ew_compound_proxy'], '')
                self.assertTrue(row['post4_weeks'].startswith('2024-W03|'))

    def test_insufficient_window_and_metric_specific_missing(self):
        row = self.build([week(n) for n in range(1, 5)])[0]
        self.assertEqual(row['post4_status'], 'MISSING_INSUFFICIENT_WEEKS')
        self.assertEqual(row['post4_mean_m_pressure'], '')
        weeks = [week(n, **({'m_pressure': ''} if n == 4 else {})) for n in range(1, 7)]
        row = self.build(weeks)[0]
        self.assertEqual(row['post4_status'], 'AVAILABLE')
        self.assertEqual(row['post4_mean_m_pressure'], '')
        self.assertEqual(row['post4_delta_m_pressure'], '')
        self.assertEqual(row['post4_mean_ax_part'], 2)
        self.assertEqual(row['post4_delta_ax_part'], 0)

    def test_no_pre_still_has_post_means_without_delta(self):
        row = self.build([week(n) for n in range(3, 7)])[0]
        self.assertEqual(row['pre_status'], 'MISSING_WITHIN_21D')
        self.assertEqual(row['post4_mean_ax_part'], 2)
        self.assertEqual(row['post4_delta_ax_part'], '')

    def test_nonobserved_holiday_not_counted_and_unknown_post_is_not_pre(self):
        weeks = [week(n) for n in range(1, 8)]
        weeks[2].update(days_obs='0', ax_days='0')
        weeks[3]['availability_unknown'] = '1'
        row = self.build(weeks)[0]
        self.assertEqual(row['post4_weeks'], '2024-W04|2024-W05|2024-W06|2024-W07')
        self.assertEqual(row['post4_status'], 'AVAILABLE')

    def test_baseline_requires_all_same_post_week_endpoints(self):
        baseline = [dict(week=f'2024-W{n:02}', coverage_status='ENDPOINT_AVAILABLE', index_week_return='0.02') for n in range(3, 7)]
        row = self.build(baseline=baseline)[0]
        self.assertAlmostEqual(row['post4_index_compound'], 1.02 ** 4 - 1)
        baseline[-1]['coverage_status'] = 'MISSING_OR_PARTIAL'
        row = self.build(baseline=baseline)[0]
        self.assertEqual(row['post4_index_compound'], '')
        self.assertNotEqual(row['post2_index_compound'], '')

    def test_pre_rejects_future_week_with_forged_early_availability(self):
        row = self.build([week(1), week(5, usable_at='2024-01-10T11:00:00+08:00')])[0]
        self.assertEqual(row['pre_week'], '2024-W01')

    def test_timestamp_and_publication_order(self):
        self.assertIsNone(timeline.timestamp('2024-01-10T09:30:00'))
        self.assertIsNotNone(timeline.timestamp('2024-01-10'))
        bad = event()
        bad['published_at'] = '2024-01-11'
        with self.assertRaises(ValueError):
            self.build(events=[bad])

    def test_invalid_seed_and_duplicate_weeks_rejected(self):
        with self.assertRaises(ValueError):
            self.build(events=[event(), event()])
        with self.assertRaises(ValueError):
            self.build(events=[event(at='bad')])
        with self.assertRaises(ValueError):
            self.build([week(1), week(1)])


if __name__ == '__main__':
    unittest.main()
