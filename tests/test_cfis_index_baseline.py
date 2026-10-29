import importlib.util
from pathlib import Path
import unittest

P = Path(__file__).resolve().parents[1] / 'scripts/cfis/is2a_index_baseline.py'
spec = importlib.util.spec_from_file_location('cfis_index', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IndexBaselineTest(unittest.TestCase):
    def test_normal_week(self):
        w = [{'week': '2024-W02', 'week_end': '20240112'}]
        r = m.build(w, [{'trade_date': '2024-01-05', 'close': 100},
                        {'trade_date': '2024-01-12', 'close': 110}])[0]
        self.assertAlmostEqual(r['index_week_return'], .1)

    def test_never_bridge_large_gap(self):
        w = [{'week': '2023-W36', 'week_end': '20230908'}]
        r = m.build(w, [{'trade_date': '2023-03-31', 'close': 100},
                        {'trade_date': '2023-09-08', 'close': 110}])[0]
        self.assertEqual(r['index_week_return'], '')
        self.assertEqual(r['coverage_status'], 'MISSING_OR_PARTIAL')

    def test_missing_endpoint(self):
        w = [{'week': '2024-W02', 'week_end': '20240112'}]
        r = m.build(w, [{'trade_date': '2024-01-05', 'close': 100},
                        {'trade_date': '2024-01-11', 'close': 110}])[0]
        self.assertEqual(r['index_week_return'], '')

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            m.build([], [{'trade_date': '2024-01-05', 'close': 100}] * 2)


if __name__ == '__main__':
    unittest.main()
