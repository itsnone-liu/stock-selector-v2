"""Isolated stdlib tests: python -m unittest discover -s tests -p test_cfis_event_windows.py."""
import csv
import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/cfis/is2a_event_windows.py"
spec = importlib.util.spec_from_file_location("cfis_event_windows", MODULE)
windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows)


def event(event_id="event1", usable="2023-04-12", cluster="cluster1"):
    return {"event_id": event_id, "title": "Test event", "event_type": "policy",
            "source_url": "https://example.org/source", "published_at": usable,
            "first_usable_at": usable, "effective_at": usable,
            "event_cluster_id": cluster, "evidence_status": "verified",
            "custom_provenance": "preserve me"}


def weeks(start=date(2023, 1, 2), count=60):
    rows = []
    for index in range(count):
        monday = start + timedelta(weeks=index)
        rows.append({"week": windows.iso_week(monday),
                     "week_end": (monday + timedelta(days=4)).strftime("%Y%m%d"),
                     "days_obs": "5", "test_metric": str(index)})
    return rows


class EventWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / "seed.json"
        self.weekly = self.root / "weekly.csv"
        self.output = self.root / "output.csv"
        self.summary = self.root / "summary.md"

    def write_seed(self, events):
        self.seed.write_text(json.dumps({"events": events, "coverage_status": "seed_not_exhaustive"}))
        return windows.load_events(self.seed)

    def write_weekly(self, rows):
        with self.weekly.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def build(self, events=None, rows=None):
        ledger, groups = self.write_seed(events if events is not None else [event()])
        return windows.build_windows(rows if rows is not None else weeks(), ledger, groups)

    def test_complete_window_and_eligibility(self):
        rows = [r for r in self.build() if r["window_kind"] == "EVENT"]
        self.assertEqual(len(rows), 21)
        self.assertEqual([r["rel_observed_week"] for r in rows], list(range(-8, 13)))
        self.assertEqual([r["test_metric"] for r in rows], [str(i) for i in range(6, 27)])
        for row in rows:
            self.assertEqual(row["feature_eligibility"], windows.ELIGIBILITY[row["phase"]])
            self.assertEqual(row["window_complete"], "true")
        self.assertEqual(rows[8]["week"], "2023-W15")
        self.assertEqual(rows[8]["phase"], "EVENT")

    def test_truncation_not_dropped(self):
        rows = self.build(rows=weeks(count=16))
        anchor = next(r for r in rows if r["phase"] == "EVENT")
        self.assertEqual(anchor["post_weeks_observed"], 1)
        self.assertIn("RIGHT_CENSORED", anchor["window_status"])
        anchor = next(r for r in self.build([event(usable="2023-01-03")]) if r["phase"] == "EVENT")
        self.assertEqual(anchor["missing_pre_weeks"], 8)
        self.assertIn("LEFT_TRUNCATED", anchor["window_status"])

    def test_holiday_weeks_count_observed_not_calendar(self):
        data = weeks()
        del data[13]
        rows = [r for r in self.build(rows=data) if r["window_kind"] == "EVENT"]
        self.assertEqual(len(rows), 21)
        self.assertEqual(rows[7]["week"], "2023-W13")
        self.assertEqual(rows[7]["rel_observed_week"], -1)

    def test_missing_event_week_keeps_explicit_anchor(self):
        data = weeks()
        del data[14]
        rows = [r for r in self.build(rows=data) if r["window_kind"] == "EVENT"]
        anchor = rows[8]
        self.assertEqual(anchor["row_status"], "MISSING_EVENT_WEEK")
        self.assertNotIn("week", anchor)
        self.assertEqual(anchor["event_iso_week"], "2023-W15")
        self.assertEqual(rows[9]["week"], "2023-W16")
        self.assertEqual(anchor["window_complete"], "false")

    def test_event_outside_data_is_retained(self):
        for usable in ("2020-01-01", "2030-01-01"):
            rows = self.build([event(usable=usable)])
            anchor = next(r for r in rows if r["phase"] == "EVENT")
            self.assertEqual(anchor["event_week_observed"], "false")
            self.assertEqual(anchor["window_complete"], "false")

    def test_cluster_earliest_representative_preserves_sources(self):
        later = event("later", "2023-04-19")
        earlier = event("earlier")
        rows = self.build([later, earlier])
        anchors = [r for r in rows if r["phase"] == "EVENT"]
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["event_id"], "earlier")
        self.assertEqual(anchors[0]["cluster_event_count"], 2)
        self.assertEqual(json.loads(anchors[0]["cluster_event_ids"]), ["earlier", "later"])
        self.assertEqual(json.loads(anchors[0]["event_metadata_json"])["custom_provenance"], "preserve me")

    def test_cluster_tie_deterministic(self):
        _, groups = self.write_seed([event("z"), event("a")])
        self.assertEqual(groups[0][0]["event_id"], "a")

    def test_duplicate_ids_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            self.write_seed([event(), event(cluster="another")])

    def test_missing_dates_fail(self):
        for field in windows.DATE_FIELDS:
            for value in (None, "", "not-a-date", "2023-02-30"):
                with self.subTest(field=field, value=value):
                    bad = event()
                    bad[field] = value
                    with self.assertRaises(ValueError):
                        self.write_seed([bad])

    def test_date_order_and_aware_timestamp(self):
        bad = event()
        bad["published_at"] = "2023-04-13"
        with self.assertRaisesRegex(ValueError, "precedes"):
            self.write_seed([bad])
        with self.assertRaisesRegex(ValueError, "timezone"):
            windows.parse_event_date("2023-04-12T10:00:00", "test")
        local = windows.parse_event_date("2023-01-01T17:00:00Z", "test")
        self.assertEqual(windows.iso_week(local), "2023-W01")
        # Effective dates are not availability timestamps.
        valid = event()
        valid["effective_at"] = "2020-01-01"
        self.write_seed([valid])

    def test_calendar_not_event_free_and_inclusive(self):
        data = weeks(count=95)
        rows = self.build(rows=data)
        for name, begin, end in windows.CALENDARS:
            selected = [r for r in rows if r["window_id"] == name]
            self.assertEqual(len(selected), 13)
            self.assertTrue(all(r["comparison_status"].endswith("NOT_EVENT_FREE_CONTROL") for r in selected))
            self.assertTrue(all(r["rel_observed_week"] == "" for r in selected))
            self.assertEqual(selected[0]["week_end"], (date.fromisoformat(begin) + timedelta(days=4)).strftime("%Y%m%d"))
            self.assertEqual(selected[-1]["week_end"], end.replace("-", ""))

    def test_weekly_validation(self):
        for data in ([weeks()[1], weeks()[0]], [weeks()[0], weeks()[0]],
                     [{**weeks()[0], "week_end": "20230120"}],
                     [{**weeks()[0], "days_obs": "0"}]):
            self.write_weekly(data)
            with self.assertRaises(ValueError):
                windows.load_weekly(self.weekly)

    def test_end_to_end_readonly_seed_and_summary(self):
        self.write_weekly(weeks(count=95))
        self.write_seed([event()])
        original = self.seed.read_bytes()
        rows = windows.run(self.weekly, self.seed, self.output, self.summary)
        self.assertEqual(original, self.seed.read_bytes())
        with self.output.open() as stream:
            saved = list(csv.DictReader(stream))
        self.assertEqual(len(saved), len(rows))
        text = self.summary.read_text()
        for term in ("禁止因果", "独立样本", "非穷尽", "不是已证无事件对照", "完整窗 1"):
            self.assertIn(term, text)

    def test_pre_context_checks_actual_availability(self):
        sample = event()
        for usable, unknown, expected in (
                ("2023-04-11T12:00:00+08:00", "0", "USABLE_BEFORE_EVENT"),
                ("2023-04-12T00:00:00+08:00", "0", "LATE_OR_AT_EVENT_NOT_PREKNOWN"),
                ("2023-04-13", "0", "LATE_OR_AT_EVENT_NOT_PREKNOWN"),
                ("", "0", "MISSING_USABLE_AT"),
                ("bad", "0", "INVALID_USABLE_AT"),
                ("2023-04-11", "1", "UNKNOWN_ATOMIC_AVAILABILITY")):
            row = {"usable_at": usable, "availability_unknown": unknown}
            self.assertEqual(windows.pre_availability(row, sample, "PRE"), expected)
        self.assertEqual(windows.pre_availability({}, sample, "EVENT"), "NOT_PRE_CONTEXT")

    def test_empty_events_keeps_calendar(self):
        rows = self.build([], weeks(count=95))
        self.assertEqual(len(rows), 26)
        self.assertTrue(all(r["window_kind"] == "CALENDAR_COMPARISON" for r in rows))


if __name__ == "__main__":
    unittest.main()
