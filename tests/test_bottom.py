from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.bottom_pool import BottomPoolStore
from stock_selector.models import Decision
from stock_selector.strategies.bottom import bottom_volume_signal


def make_bottom_daily(days: int = 300, base_price: float = 20.0) -> pd.DataFrame:
    """构造：深回撤+低位平台+安静量，最后一日三倍量大涨。"""
    index = pd.bdate_range(end="2026-09-15", periods=days)
    rng = np.random.default_rng(7)
    # 前250日在高位震荡后跌到低位，近60日低位横盘
    high_phase = base_price * (1.0 + 0.02 * np.sin(np.arange(250) / 25.0))
    decline = np.linspace(base_price, base_price * 0.62, 40)
    platform = base_price * 0.62 + 0.05 * np.sin(np.arange(days - 290) / 5.0) + rng.normal(0, 0.03, days - 290)
    close = np.concatenate([high_phase, decline, platform])
    close[-1] = close[-2] * 1.068  # 大涨6.8%，收阳
    open_ = close - 0.02
    open_[-1] = close[-1] - close[-1] * 0.02
    low = np.minimum(open_, close) - 0.05
    low[-1] = open_[-1] + (close[-1] - open_[-1]) * 0.2  # 收盘位于振幅上部
    high = np.maximum(open_, close) + 0.05
    volume = np.full(days, 1_000_000.0)
    volume[-6:] = 950_000.0
    volume[-1] = 3_200_000.0  # 前5日均量的3倍以上
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": close * volume},
        index=index,
    )


def test_bottom_volume_signal_fires(config):
    result = bottom_volume_signal(make_bottom_daily(), config)
    assert result.decision is Decision.PASS
    assert result.metrics["volume_multiple"] >= 3.0
    assert result.metrics["day_change_pct"] >= 6.0


def test_bottom_volume_rejects_already_rallied(config):
    daily = make_bottom_daily()
    closes = daily["close"].copy()
    closes.iloc[-21:-1] = closes.iloc[-21:-1] * np.linspace(1.0, 1.18, 20)
    daily["close"] = closes
    daily.iloc[-1, daily.columns.get_loc("close")] = closes.iloc[-2] * 1.07
    daily.iloc[-1, daily.columns.get_loc("open")] = daily.iloc[-1]["close"] * 0.98
    result = bottom_volume_signal(daily, config)
    # 前20日已累计上涨：或已超15%上限，或价格已脱离低位平台/回撤变浅
    assert result.decision is Decision.REJECT
    assert result.reason in {"prelaunch_out_of_range", "above_low_platform", "drawdown_too_shallow"}


def test_bottom_volume_rejects_low_volume(config):
    daily = make_bottom_daily()
    daily.iloc[-1, daily.columns.get_loc("volume")] = 1_800_000.0
    result = bottom_volume_signal(daily, config)
    assert result.decision is Decision.REJECT
    assert result.reason == "volume_multiple_too_low"


def test_pool_state_machine(tmp_path):
    store = BottomPoolStore(tmp_path / "events.csv")
    store.append(
        [
            {
                "代码": "000001",
                "名称": "测试",
                "事件日": "2026-09-10",
                "事件日最低": 9.5,
                "状态": "active",
            }
        ]
    )
    daily = pd.DataFrame(
        {"close": [10.0, 9.4, 9.2], "volume": [1e6, 1e6, 1e6]},
        index=pd.bdate_range(end="2026-09-15", periods=3),
    )
    counts = store.refresh(lambda code: daily, datetime(2026, 9, 15, 15, 0), 60)
    assert counts["invalidated"] == 1
    assert store.active().empty

    store2 = BottomPoolStore(tmp_path / "events2.csv")
    rising = pd.DataFrame(
        {"close": [10.0 + i * 0.1 for i in range(70)], "volume": [1e6] * 70},
        index=pd.bdate_range(end="2026-09-15", periods=70),
    )
    store2.append(
        [
            {
                "代码": "000002",
                "事件日": str(pd.Timestamp(rising.index[3]).date()),
                "事件日最低": float(rising["low"].iloc[3]) if "low" in rising.columns else 10.3,
                "状态": "active",
            }
        ]
    )
    counts2 = store2.refresh(lambda code: rising, datetime(2026, 9, 15, 15, 0), 60)
    assert counts2["expired"] == 1

    store3 = BottomPoolStore(tmp_path / "events3.csv")
    store3.append([{"代码": "000003", "事件日": "2026-09-10", "事件日最低": 9.5, "状态": "active"}])
    store3.mark_converted(["000003"], datetime(2026, 9, 15, 15, 0).date())
    frame = store3.load()
    assert frame.iloc[0]["状态"] == "converted"
    assert frame.iloc[0]["转化日"] == "2026-09-15"


def test_pool_refresh_ignores_future_bars_beyond_asof(tmp_path):
    """T3：状态机刷新受显式 asof 约束——数据源里 asof 之后的未来行
    （哪怕跌破事件日低点、哪怕超出过期天数）不得驱动 invalidated/expired。"""
    store = BottomPoolStore(tmp_path / "events.csv")
    store.append([{"代码": "000001", "名称": "测试", "事件日": "2026-09-10", "事件日最低": 9.5, "状态": "active"}])
    # 帧里 2026-09-16（asof=2026-09-15 之后）出现破位阴线与超期长度，但 asof 之前走势完好
    index = list(pd.bdate_range(end="2026-09-15", periods=4)) + [pd.Timestamp("2026-09-16"), pd.Timestamp("2026-09-17")]
    daily = pd.DataFrame(
        {"close": [10.0, 10.1, 10.2, 10.3, 9.0, 8.0], "volume": [1e6] * 6},
        index=pd.DatetimeIndex(index),
    )
    counts = store.refresh(lambda code: daily, datetime(2026, 9, 15, 15, 0), 60)
    assert counts == {"invalidated": 0, "expired": 0, "checked": 1}
    assert store.active()["代码"].tolist() == ["000001"]
    # asof 推进到未来行之后：同一帧正常失效
    counts_later = store.refresh(lambda code: daily, datetime(2026, 9, 17, 15, 0), 60)
    assert counts_later["invalidated"] == 1
    assert store.active().empty


def test_pool_refresh_expires_only_on_bars_visible_at_asof(tmp_path):
    """T3：过期计数同样只数 asof（含）之前的交易日。"""
    store = BottomPoolStore(tmp_path / "events.csv")
    index = pd.bdate_range(end="2026-09-15", periods=70)
    store.append(
        [{"代码": "000002", "事件日": str(index[3].date()), "事件日最低": 10.0, "状态": "active"}]
    )
    rising = pd.DataFrame({"close": np.linspace(10.0, 17.0, 70), "volume": [1e6] * 70}, index=index)
    # asof 截到第 64 根：事件后可见 60 根 → 仍 active（len(after)==60 未“超过”60）
    asof = index[63]
    counts = store.refresh(lambda code: rising, asof.to_pydatetime(), 60)
    assert counts == {"invalidated": 0, "expired": 0, "checked": 1}
    # asof 截到第 65 根：事件后可见 61 根 → expired
    counts2 = store.refresh(lambda code: rising, index[64].to_pydatetime(), 60)
    assert counts2["expired"] == 1


def test_cli_rejects_bottom_realtime_without_select(capsys):
    """T3：--realtime 仅在 --select（小金叉通道）下有效，缺 --select 时校验即报错（fail loud）。

    校验在完整解析后执行（validate_args），与选项书写顺序无关：
    `--select --realtime` 与 `--realtime --select` 必须同被接受且解析结果一致。
    """
    from stock_selector.cli import build_parser, validate_args

    def run(argv):
        parser = build_parser()
        args = parser.parse_args(argv)
        validate_args(parser, args)
        return args

    # 缺 --select：exit 2，报错指明用法
    parser = build_parser()
    args = parser.parse_args(["bottom-volume", "--realtime"])
    with pytest.raises(SystemExit) as exc:
        validate_args(parser, args)
    assert exc.value.code == 2
    assert "--select" in capsys.readouterr().err

    # 两种书写顺序都必须通过且解析结果一致
    a = run(["bottom-volume", "--select", "--realtime"])
    b = run(["bottom-volume", "--realtime", "--select"])
    assert a.select is True and a.realtime is True
    assert (a.select, a.realtime) == (b.select, b.realtime)

    # 纯盘后扫描不受影响；未指定 --realtime 时默认值为布尔 False（P1：契约稳定）
    c = run(["bottom-volume"])
    assert c.select is False and c.realtime is False


def test_pool_delayed_refresh_expiry_beats_late_break(tmp_path):
    """T3 状态竞争：事件后前60日不破位、第61日达过期边界、第70日才破位。
    延迟一次刷新到第70日 → 终态必须是 expired（过期先生效），不得 invalidated。"""
    store = BottomPoolStore(tmp_path / "events.csv")
    n = 70
    index = pd.bdate_range(end="2026-09-15", periods=n)
    closes = np.full(n, 12.0)  # 事件价上方横盘，全程不破位……
    closes[-1] = 9.0  # ……只有第 70 日（最后一根）破位
    daily = pd.DataFrame({"close": closes, "volume": [1e6] * n}, index=index)
    store.append([{"代码": "000001", "事件日": str(index[0].date()), "事件日最低": 10.0, "状态": "active"}])
    # asof = 第 70 根（事件后第 70 个可见交易日）：过期于第 61 根已生效
    counts = store.refresh(lambda code: daily, index[-1].to_pydatetime(), 60)
    assert counts == {"invalidated": 0, "expired": 1, "checked": 1}
    frame = store.load()
    assert frame.iloc[0]["状态"] == "expired"
    assert frame.iloc[0]["失效日"] == ""


def test_pool_early_break_beats_already_passed_expiry(tmp_path):
    """T3 状态竞争（反向）：60日窗口内先跌破，asof 已越过过期边界 → 仍必须 invalidated，
    且失效日 = 首次跌破日（不是刷新日）。"""
    store = BottomPoolStore(tmp_path / "events.csv")
    n = 70
    index = pd.bdate_range(end="2026-09-15", periods=n)
    closes = np.full(n, 12.0)
    closes[9] = 9.5  # 事件后第 10 根首次跌破（10.0 事件低点）
    closes[10:] = 11.5  # 随后收回——首次破位已不可逆
    daily = pd.DataFrame({"close": closes, "volume": [1e6] * n}, index=index)
    store.append([{"代码": "000001", "事件日": str(index[0].date()), "事件日最低": 10.0, "状态": "active"}])
    counts = store.refresh(lambda code: daily, index[-1].to_pydatetime(), 60)
    assert counts == {"invalidated": 1, "expired": 0, "checked": 1}
    frame = store.load()
    assert frame.iloc[0]["状态"] == "invalidated"
    assert frame.iloc[0]["失效日"] == str(index[9].date())


def test_pool_break_exactly_at_expiry_bar_counts_as_invalidated(tmp_path):
    """T3 状态竞争（同日并列）：第 61 根（过期生效当根）恰好首次破位 → invalidated（并列时破位优先）。"""
    store = BottomPoolStore(tmp_path / "events.csv")
    n = 61
    index = pd.bdate_range(end="2026-09-15", periods=n)
    closes = np.full(n, 12.0)
    closes[-1] = 9.0  # 第 61 根（0-based 60 == expiry_pos）首次破位
    daily = pd.DataFrame({"close": closes, "volume": [1e6] * n}, index=index)
    store.append([{"代码": "000001", "事件日": str(index[0].date()), "事件日最低": 10.0, "状态": "active"}])
    counts = store.refresh(lambda code: daily, index[-1].to_pydatetime(), 60)
    assert counts["invalidated"] == 1 and counts["expired"] == 0
    assert store.load().iloc[0]["失效日"] == str(index[-1].date())
