from datetime import datetime

from stock_selector.data.realtime import TencentQuoteProvider, _symbol


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


def test_tencent_volume_is_normalized_from_hands_to_shares():
    provider = TencentQuoteProvider(volume_multiplier=100)
    provider.session = FakeSession()
    quotes, errors = provider.fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert not errors
    assert quotes["600001"].volume == 123400
    assert quotes["600001"].timestamp == datetime(2026, 9, 15, 10, 0)
