import pandas as pd

from stock_selector.output import write_csv


def test_atomic_csv_preserves_leading_zero_on_read_as_text(tmp_path):
    path = write_csv(pd.DataFrame([{"代码": "000001", "值": 1}]), tmp_path / "x.csv")
    text = path.read_text(encoding="utf-8-sig")
    assert "000001" in text
    assert not list(tmp_path.glob("tmp*"))
