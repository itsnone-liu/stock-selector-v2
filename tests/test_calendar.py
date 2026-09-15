from datetime import datetime

import pandas as pd

from stock_selector.calendar import completed_week_rows, current_week_rows, elapsed_session_fraction, elapsed_week_fraction


def test_week_partition_never_guesses_last_row():
    frame = pd.DataFrame({"close": range(7)}, index=pd.to_datetime(["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"]))
    at = datetime(2026, 9, 15, 11, 0)
    assert list(current_week_rows(frame, at).index.date) == [at.date().replace(day=14), at.date()]
    assert list(completed_week_rows(frame, at).index.date)[-1].isoformat() == "2026-09-11"


def test_elapsed_session_fraction_handles_lunch_and_close():
    assert elapsed_session_fraction(datetime(2026, 9, 15, 9, 0)) == 0
    assert elapsed_session_fraction(datetime(2026, 9, 15, 11, 30)) == 0.5
    assert elapsed_session_fraction(datetime(2026, 9, 15, 12, 30)) == 0.5
    assert elapsed_session_fraction(datetime(2026, 9, 15, 15, 30)) == 1


def test_elapsed_week_fraction_uses_completed_days_plus_intraday():
    frame = pd.DataFrame({"close": [1]}, index=pd.to_datetime(["2026-09-14"]))
    fraction = elapsed_week_fraction(frame, datetime(2026, 9, 15, 11, 30), realtime=True)
    assert fraction == 0.3
