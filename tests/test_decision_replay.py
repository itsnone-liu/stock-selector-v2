"""决策栈测试：PIT截断、防穿越、回放确定性、分钟构造。"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.decision.minutes import SyntheticMinuteProvider, TdxMinuteReader, _decode_date
from stock_selector.decision.replay import DecisionService, PITReplay, quote_from_minutes, truncate_daily
from tests.test_decision_core import make_daily, week_frame


def _loader(frames: dict[str, pd.DataFrame]):
    return lambda code: frames.get(code)


def _service(frames: dict[str, pd.DataFrame], index: pd.DataFrame | None = None, minute=False) -> DecisionService:
    provider = None
    if minute:
        provider = SyntheticMinuteProvider(_loader(frames))
    return DecisionService(
        config={"monthly": {"min_bars": 20}, "weekly": {"min_bars": 35},
                "surge": {}, "buy": {}, "decision": {}},
        daily_loader=_loader(frames),
        index_loader=(lambda: index) if index is not None else None,
        minute_provider=provider,
    )


class TestTruncation:
    def test_intraday_excludes_today(self):
        frame = make_daily([10 + i * 0.1 for i in range(10)], end="2026-09-16")
        truncated = truncate_daily(frame, datetime(2026, 9, 16, 10, 30))
        assert pd.Timestamp(truncated.index[-1]).date() == date(2026, 9, 15)

    def test_after_close_includes_today(self):
        frame = make_daily([10 + i * 0.1 for i in range(10)], end="2026-09-16")
        truncated = truncate_daily(frame, datetime(2026, 9, 16, 15, 10))
        assert pd.Timestamp(truncated.index[-1]).date() == date(2026, 9, 16)


class TestQuoteFromMinutes:
    def test_synthetic_quote(self):
        daily = make_daily([10, 10.5, 11.0], end="2026-09-16")
        provider = SyntheticMinuteProvider(_loader({"600000": daily}))
        minutes = provider.minute_frame("600000", date(2026, 9, 16))
        assert minutes is not None and len(minutes) == 240
        asof = datetime(2026, 9, 16, 10, 30)  # 60分钟
        quote = quote_from_minutes("600000", minutes, daily, asof)
        assert quote is not None
        assert quote.previous_close == pytest.approx(10.5)
        assert quote.open == pytest.approx(10.5, abs=1e-6)
        # 合成路径线性：≤10:30 含10:30整分K=61根 → 61/240处价格
        # make_daily当日: open=昨收10.5, close=11.0
        expected = 10.5 + (11.0 - 10.5) * 61 / 240
        assert quote.price == pytest.approx(expected, abs=1e-6)
        assert quote.volume == pytest.approx(float(daily["volume"].iloc[-1]) * 61 / 240, rel=1e-6)


class TestAntiLookahead:
    def _core(self, advice: dict) -> str:
        """剥离时间戳后的可比核心（as_of本身不算穿越证据）。"""
        d = copy.deepcopy(advice)
        d.pop("as_of", None)
        d.get("evidence", {}).pop("session_completion", None)
        return json.dumps(d, sort_keys=True, ensure_ascii=False)

    def test_future_daily_mutation_does_not_change_advice(self):
        frame = week_frame(prev_week_pct=4.0, weeks=16)
        frames = {"600000": frame.copy()}
        service = _service(frames)
        t1 = datetime(2026, 9, 15, 15, 10)
        base = service.evaluate("600000", t1)
        # 篡改 T1 之后的所有数据（暴涨/暴跌/爆量）
        mutated = frame.copy()
        mutated.iloc[-1, mutated.columns.get_loc("close")] *= 0.5
        mutated.iloc[-1, mutated.columns.get_loc("volume")] *= 10
        mutated.iloc[-2, mutated.columns.get_loc("close")] *= 1.5
        service2 = _service({"600000": mutated})
        again = service2.evaluate("600000", t1)
        assert self._core(base) == self._core(again)

    def test_future_index_mutation_does_not_change_regime(self):
        idx = make_daily([3000 + i * 5 for i in range(120)], end="2026-09-18")
        frame = week_frame(prev_week_pct=4.0, weeks=16)
        service = _service({"600000": frame.copy()}, index=idx.copy())
        t1 = datetime(2026, 9, 15, 15, 10)
        base = service.evaluate("600000", t1)
        idx2 = idx.copy()
        idx2.iloc[-1, idx2.columns.get_loc("close")] = 1000  # T1后暴跌
        service2 = _service({"600000": frame.copy()}, index=idx2)
        again = service2.evaluate("600000", t1)
        assert base["evidence"]["market_regime"] == again["evidence"]["market_regime"]

    def test_intraday_later_minutes_do_not_leak(self):
        daily = week_frame(prev_week_pct=4.0, weeks=16)
        frames = {"600000": daily}
        provider = SyntheticMinuteProvider(_loader(frames))
        asof = datetime(2026, 9, 16, 10, 30)
        minutes = provider.minute_frame("600000", date(2026, 9, 16))
        q1 = quote_from_minutes("600000", minutes, daily, asof)
        # 篡改 10:30 之后的分钟（未来分钟存在但不得泄漏进 as_of 建议）
        corrupted = minutes.copy()
        later = corrupted.index > pd.Timestamp(asof)
        corrupted.loc[later, "close"] = corrupted.loc[later, "close"] * 5
        corrupted.loc[later, "volume"] = corrupted.loc[later, "volume"] * 50
        q2 = quote_from_minutes("600000", corrupted, daily, asof)
        assert q1.price == q2.price
        assert q1.volume == q2.volume


class TestReplayDeterminism:
    def test_repeat_run_identical(self, tmp_path):
        frame = week_frame(prev_week_pct=4.0, weeks=16)
        idx = make_daily([3000 + i * 3 for i in range(120)], end="2026-09-16")
        service = _service({"600000": frame}, index=idx)
        replay = PITReplay(service)
        asofs = [datetime(2026, 9, d, 15, 10) for d in (9, 10, 11, 14, 15)]
        r1 = replay.run(["600000"], asofs, output_path=str(tmp_path / "a.jsonl"))
        r2 = replay.run(["600000"], asofs, output_path=str(tmp_path / "b.jsonl"))
        assert [json.dumps(a, sort_keys=True) for a in r1.advices] == [json.dumps(a, sort_keys=True) for a in r2.advices]
        assert (tmp_path / "a.jsonl").read_text() == (tmp_path / "b.jsonl").read_text()
        assert len(r1.advices) == 5

    def test_advice_schema_fields(self):
        frame = week_frame(prev_week_pct=4.0, weeks=16)
        idx = make_daily([3000 + i * 3 for i in range(120)], end="2026-09-16")
        service = _service({"600000": frame}, index=idx)
        advice = service.evaluate("600000", datetime(2026, 9, 15, 15, 10))
        for key in ("schema_version", "as_of", "symbol", "action", "confidence",
                    "evidence", "unknowns", "invalidation", "versions", "rationale"):
            assert key in advice
        assert advice["schema_version"] == "1"
        assert advice["evidence"]["weekly_momentum"]["state"]
        assert "momentum_velocity" in advice["evidence"]["weekly_momentum"]["metrics"] or \
            advice["evidence"]["weekly_momentum"]["metrics"]


class TestTdxMinuteReader:
    def test_decode_date(self):
        # 2026-09-15 → (2026-2004)*2048 + 9*100 + 15
        word = (2026 - 2004) * 2048 + 9 * 100 + 15
        assert _decode_date(word) == (2026, 9, 15)

    def test_missing_file_returns_none(self, tmp_path):
        reader = TdxMinuteReader(str(tmp_path))
        assert reader.frame("600000") is None
