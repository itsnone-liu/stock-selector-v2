from stock_selector.strategies.risk import check_risk_filters
from conftest import make_daily


def test_excludes_b_shares(config):
    result = check_risk_filters("900910", "", make_daily(), config)
    assert result.reason == "b_share_excluded"


def test_excludes_st(config):
    result = check_risk_filters("600001", "*ST测试", make_daily(), config)
    assert result.reason == "st_or_delisting_excluded"


def test_accepts_liquid_normal_stock(config):
    assert check_risk_filters("600001", "正常公司", make_daily(), config).passed
