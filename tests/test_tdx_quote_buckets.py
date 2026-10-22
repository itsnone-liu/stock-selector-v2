"""tdx_quotes 分桶口径单测（离线）：missing=服务器不返回，price<=0≠停牌。

口径来源：2026-10-22 R4/R5 对拍 C-1/C-2/C-3 定案 —— 盘前 09:10 全市场请求 5598 只、
返回 5576 只且 5576/5576 全部 price=0/vol=0/servertime=8:35。所以：
  missing  = 请求集里**没有响应记录** → 停牌/无行情（fail-closed，不猜不补）
  no_price = 有记录但 price<=0 → 盘前/竞价未撮合，**不是**停牌，单列
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from r2.tdx_quotes import lookup, split_quotes

ROOT = Path(__file__).resolve().parents[1]


def q(**prices):
    return {k.replace('_', ''): {'price': v} for k, v in prices.items()}


def test_missing_is_absence_not_zero_price():
    ok, missing, no_price = split_quotes({'600125': {'price': 5.0}, '000001': {'price': 0.0}},
                                        ['600125', '000001', '601006'])
    assert set(ok) == {'600125'}
    assert missing == ['601006']       # 服务器没返回 → 停牌/无行情
    assert no_price == ['000001']      # 有记录但未撮合 → 不能算停牌


def test_preopen_all_zero_price_is_not_missing():
    """C-1 反例：盘前全零价 + 有记录，missing 必须为空。"""
    codes = ['600125', '000001', '601006']
    ok, missing, no_price = split_quotes({c: {'price': 0.0} for c in codes}, codes)
    assert missing == []
    assert ok == {}
    assert sorted(no_price) == sorted(codes)


def test_split_is_consistent_with_request_set():
    """三个桶互不相交，且并集 == 请求集（不重不漏）。"""
    codes = ['600125', '000001', '601006', '920002']
    q_ = {'600125': {'price': 1.0}, '000001': {'price': 0.0}}
    ok, missing, no_price = split_quotes(q_, codes)
    assert sorted(list(ok) + missing + no_price) == sorted(codes)
    assert not (set(ok) & set(missing)) and not (set(ok) & set(no_price)) and not (set(missing) & set(no_price))


def test_explicit_missing_arg_is_respected():
    ok, missing, no_price = split_quotes({}, ['600125'], missing=['bj920002'])
    assert (ok, missing, no_price) == ({}, ['bj920002'], [])


@pytest.mark.parametrize('bad', [None, '', '  ', 'abc', float('nan'), float('inf'), float('-inf')])
def test_unparseable_or_non_finite_price_fails_closed(bad):
    """非数值/NaN/Inf 价格 = 传输或解析损坏 → 必须报错，不能被静默归入 no_price 或入榜。"""
    with pytest.raises(ValueError):
        split_quotes({'600125': {'price': bad}}, ['600125'])


def test_row_without_price_key_fails_closed():
    with pytest.raises(ValueError):
        split_quotes({'600125': {}}, ['600125'])


def test_empty_request():
    assert split_quotes({}, []) == ({}, [], [])


def test_codes_accept_int_and_prefixed_forms():
    ok, _, _ = split_quotes({'600125': {'price': 7.0}}, [600125])
    assert set(ok) == {'600125'}
    assert split_quotes({'000001': {'price': 7.0}}, ['sz000001'])[0] == {'000001': {'price': 7.0}}


def test_cross_market_collision_uses_full_key():
    """同一 6 位码出现在两个市场时必须用全码键，不能互相覆盖。"""
    q_ = {'sh000001': {'price': 3500.0}, 'sz000001': {'price': 11.4}}
    ok, missing, no_price = split_quotes(q_, ['sh000001', 'sz000001'])
    assert missing == [] and no_price == []
    assert set(ok) == {'sh000001', 'sz000001'}
    assert ok['sh000001']['price'] == 3500.0 and ok['sz000001']['price'] == 11.4


def test_lookup_accepts_both_forms():
    m = {'600125': {'price': 5.0}, 'sh000001': {'price': 3500.0}}
    assert lookup(m, '600125')['price'] == 5.0
    assert lookup(m, 'sh600125')['price'] == 5.0
    assert lookup(m, 'sh000001')['price'] == 3500.0
    assert lookup(m, '000001')['price'] == 3500.0   # 全码键在 m 里 → 可回退命中
    assert lookup(m, '601006') is None


def test_intraday_scripts_use_the_shared_regime():
    """回归护栏：两处盘中脚本必须走 split_quotes，且旧「price<=0 判停牌」写法不得复活。"""
    for rel in ('src/r2/intraday_scan.py', 'scripts/intraday_p3rank.py'):
        src = (ROOT / rel).read_text(encoding='utf-8')
        assert 'split_quotes' in src, rel
        assert 'last_missing as _tdx_missing' not in src, rel
        assert not re.search(r"if\s+t\['price'\]\s*<=\s*0\s*:", src), rel
        assert not re.search(r"t\['price'\]\s*<=\s*0", src), rel