"""Calendar bypass regressions against the frozen 33-outcome research sample."""
import copy
import importlib.util
import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calendar_comparison', ROOT / 'scripts/cfis/is2b_calendar_comparison.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CalendarComparisonTests(unittest.TestCase):
    def setUp(self):
        self.outcomes = m.read_csv(ROOT / 'data/cfis/is2b_node_outcomes.csv')
        self.nodes = m.read_csv(ROOT / 'data/cfis/is2b_nodes.csv')
        self.weeks = m.read_csv(ROOT / 'data/cfis/weekly_full_202201_202610.csv')
        self.index = json.loads((ROOT / 'docs/phase_i/evidence/market_index_000985.json').read_text())['rows']
        self.evidence = json.loads((ROOT / 'docs/research/cfis/calendar_evidence.json').read_text())

    def run_comparison(self):
        return m.compare(self.outcomes, self.nodes, self.weeks, self.index, self.evidence)

    def test_holiday_recovers_exact_two_and_recomputes_original_ohlc(self):
        rows = self.run_comparison()
        recovered = [r for r in rows if r['old_status'] != r['new_status']]
        self.assertEqual(len(rows), 33)
        self.assertEqual([(r['week'], r['stage'], int(r['horizon'])) for r in recovered],
                         [('2024-W01', 'A', 8), ('2024-W01', 'A', 12)])
        for r, count, ret in zip(recovered, [39, 57],
                                [.00035246527283394613, .016253084071137236]):
            self.assertEqual(r['status'], 'COMPLETE')
            self.assertEqual(r['observed_days'], count)
            self.assertAlmostEqual(r['return'], ret)
            self.assertAlmostEqual(r['MAE'], -.1676520910994348)
            self.assertEqual(r['first_5pct_days'], '')
            self.assertEqual(r['hit_5pct'], 0)
            self.assertEqual(r['evidence_id'], self.evidence['evidence_id'])

    def test_daily_dates_not_naive_week_end_gap(self):
        a, b = date(2024, 2, 8), date(2024, 2, 23)
        days = {m.original.as_date(r['trade_date']) for r in self.index}
        self.assertEqual((b - a).days, 15)
        self.assertTrue(m.proven_gap(a, b, days, self.evidence))
        self.assertFalse(m.proven_gap(a, b, {a, b}, self.evidence))
        self.assertFalse(m.proven_gap(a, b, days - {date(2024, 2, 20)}, self.evidence))

    def test_unproven_2023_gaps_and_nonweekly_statuses_unchanged(self):
        # Even a real prior-year Spring Festival cannot borrow 2024 evidence.
        self.assertFalse(m.proven_gap(date(2023, 1, 20), date(2023, 2, 6),
                                      set(), self.evidence))
        for old, new in zip(self.outcomes, self.run_comparison()):
            if old['week'].startswith('2023') or old['status'] != 'WEEKLY_GAP':
                self.assertEqual({k: new[k] for k in old}, old)
                self.assertEqual(new['evidence_id'], '')

    def test_original_complete_every_field_unchanged(self):
        complete = 0
        for old, new in zip(self.outcomes, self.run_comparison()):
            if old['status'] == 'COMPLETE':
                complete += 1
                self.assertEqual({k: new[k] for k in old}, old)
        self.assertGreater(complete, 0)

    def test_source_inputs_not_mutated(self):
        values = (self.outcomes, self.nodes, self.weeks, self.index, self.evidence)
        before = copy.deepcopy(values)
        self.run_comparison()
        self.assertEqual(values, before)

    def test_missing_endpoint_guard_cannot_be_masked_by_weekly_gap(self):
        # 2/23 endpoint remains in weekly selection, but is absent in daily OHLC.
        self.index = [r for r in self.index if m.original.as_date(r['trade_date']) != date(2024, 2, 23)]
        rows = self.run_comparison()
        self.assertFalse(any(r['old_status'] != r['new_status'] for r in rows))

    def test_other_guard_missing_weekly_cannot_be_masked(self):
        # Drop a week with real index data inside both candidate windows.
        self.weeks = [r for r in self.weeks if r['week'] != '2024-W04']
        rows = self.run_comparison()
        self.assertFalse(any(r['old_status'] != r['new_status'] for r in rows))

    def test_incomplete_window_rejected(self):
        for r in self.outcomes:
            if r['status'] == 'WEEKLY_GAP':
                r['window_weeks'] = r['window_weeks'].split(';')[0]
        self.assertFalse(any(r['old_status'] != r['new_status'] for r in self.run_comparison()))


if __name__ == '__main__':
    unittest.main()
