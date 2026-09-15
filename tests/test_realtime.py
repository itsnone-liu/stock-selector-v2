from datetime import datetime

from stock_selector.data.realtime import TencentQuoteProvider


class FakeResponse:
    encoding = None
    text = 'v_sh600001="1~测试~600001~10.20~10.00~10.10~1234~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0";'

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


def test_tencent_volume_is_normalized_from_hands_to_shares():
    provider = TencentQuoteProvider(volume_multiplier=100)
    provider.session = FakeSession()
    quotes, errors = provider.fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert not errors
    assert quotes["600001"].volume == 123400
