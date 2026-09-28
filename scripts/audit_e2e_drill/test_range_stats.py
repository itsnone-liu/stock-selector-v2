"""unittest coverage for clamp_range (frozen task packet aa0eaf122ba0, stage T1)."""

import unittest

from range_stats import clamp_range


class ClampRangeTests(unittest.TestCase):

    def test_regular_range_filter(self):
        self.assertEqual(clamp_range([3, 1, 2, 7, 0], 1, 3), [1, 2, 3])

    def test_empty_list_returns_empty(self):
        self.assertEqual(clamp_range([], 0, 10), [])

    def test_none_input_returns_empty(self):
        self.assertEqual(clamp_range(None, 0, 10), [])

    def test_all_nan_excluded(self):
        self.assertEqual(clamp_range([float('nan'), float('nan')], 0, 10), [])

    def test_lo_greater_than_hi_returns_empty(self):
        self.assertEqual(clamp_range([1, 5, 9], 10, 0), [])

    def test_dedup_and_ascending(self):
        self.assertEqual(clamp_range([5, 3, 5, 1, 3, 9, 1], 0, 10), [1, 3, 5, 9])


if __name__ == '__main__':
    unittest.main()
