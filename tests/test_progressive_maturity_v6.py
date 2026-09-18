import pandas as pd

from scripts.run_progressive_analysis import group_summary


def test_next_week_summary_excludes_unmatured_rows():
    frame = pd.DataFrame({
        "cohort": ["eligible", "eligible"],
        "fwd1": [0.0, 0.0], "industry_excess1": [0.0, 0.0],
        "matured_week": [True, False],
        "next_week_return": [0.10, -0.90],
    })
    out = group_summary(frame, (1,), comparison="weekly_direct_within_monthly",
                        sample_kind="all")
    row = out.iloc[0]
    assert row["next_week_n"] == 1
    assert row["next_week_median"] == 0.10
    assert row["next_week_mean"] == 0.10
    assert row["next_week_positive_rate"] == 1.0
