from datetime import datetime

from stock_selector.data.realtime import TdxQuoteProvider, TencentQuoteProvider, _symbol


class FakeResponse:
    encoding = None
    fields = ["0"] * 37
    fields[0:7] = ["1", "测试", "600001", "10.20", "10.00", "10.10", "1234"]
    fields[30] = "20260915100000"
    text = 'v_sh600001="' + "~".join(fields) + '";'

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


def test_market_prefix_mapping_includes_bj_920_and_sh_b_share():
    assert _symbol("920001") == "bj920001"
    assert _symbol("900910") == "sh900910"
    assert _symbol("688001") == "sh688001"
    assert _symbol("000001") == "sz000001"


def test_tdx_quote_provider_uses_cumulative_minutes(monkeypatch):
    from stock_selector.data.tdx_live import TdxBar

    class FakeClient:
        def __init__(self, host=None): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def fetch(self, code, period, start, count):
            if period == "daily":
                return [TdxBar("20260914", 10, 10, 10, 10, 1000, 100),
                        TdxBar("20260915", 10.1, 10.3, 10, 10.2, 1000, 100)]
            return [TdxBar("202609150931", 10.1, 10.2, 10, 10.15, 500, 50),
                    TdxBar("202609151000", 10.15, 10.3, 10.1, 10.2, 700, 70)]

    monkeypatch.setattr("stock_selector.data.realtime.TdxLiveClient", FakeClient)
    quotes, errors = TdxQuoteProvider(max_workers=1).fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert not errors
    quote = quotes["600001"]
    assert quote.price == 10.2
    assert quote.previous_close == 10
    assert quote.volume == 120
    assert quote.amount == 1200
    assert quote.timestamp == datetime(2026, 9, 15, 10, 0)


def test_tencent_volume_is_normalized_from_hands_to_shares():
    provider = TencentQuoteProvider(volume_multiplier=100)
    provider.session = FakeSession()
    quotes, errors = provider.fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert not errors
    assert quotes["600001"].volume == 123400
    assert quotes["600001"].timestamp == datetime(2026, 9, 15, 10, 0)
