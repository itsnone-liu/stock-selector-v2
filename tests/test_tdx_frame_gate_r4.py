"""R4 实测字节回放：帧长度闸门 + 声明/解析记录数闸门（离线、无网络）。

断言全部跑在 2026-10-22 竞价五个成功采集点的**真实字节**上（09:24:55 … 09:30:06），
所以闸门的两半（字节计数、声明条数 vs 解析条数）是对着现实校验的，而不是自造帧。
第六个点 09:27:55 是客户端侧 "truncated response" 的那一次，没有 response/clear 对，
因此不在 manifest 里 —— 下面的「流被截短」用例就是那次失败在 exact()/_recv() 眼里的样子。

来源：R4/R5 差异清单 D8 / C-1 / C-3（docs/R4R5_DIFF_LIST_20261022.md）。
本文件与 tdx-protocol/realclient/test_frame_gate.py 同构，两仓必须同步修改。
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from r2.tdx_client import _exact, _recv, _unwrap_frame, check_quote_count

FX = Path(__file__).resolve().parent / 'fixtures' / 'r4_20261022'
MAN = json.loads((FX / 'manifest.json').read_text())
FAILED_POINT = '09_27_55_092755_000'  # 客户端侧截断，未采到 response/clear 对
POINTS = sorted(MAN)


def load(tag):
    return (FX / f'{tag}_response.bin').read_bytes(), (FX / f'{tag}_clear.bin').read_bytes()


def parse_quotes(clear, stocks):
    """用生产解码器解真实响应体（socket 不参与，传 None）。"""
    from tdxpy.parser.std.get_security_quotes import GetSecurityQuotesCmd

    cmd = GetSecurityQuotesCmd(None)
    cmd.setParams([(m, c) for m, c in stocks])
    return cmd.parseResponse(clear) or []


class Stream:
    """最小 socket 替身：发完字节后报 EOF。"""

    def __init__(self, data):
        self.buf = bytearray(data)

    def recv(self, n):
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def test_fixture_set_is_the_five_ok_points():
    assert len(MAN) == 5
    assert FAILED_POINT not in MAN


@pytest.mark.parametrize('tag', POINTS)
def test_byte_count_identity_holds(tag):
    resp, clear = load(tag)
    packed, raw = struct.unpack_from('<HH', resp, 12)
    assert packed == len(resp) - 16, 'header packed != 实际 body 字节数'
    assert raw == len(clear), 'header raw_len != clear 长度'
    assert packed == MAN[tag]['packed']
    assert len(clear) == MAN[tag]['clear_bytes']
    assert _unwrap_frame(resp[16:], packed, raw) == clear


@pytest.mark.parametrize('tag', POINTS)
def test_declared_count_equals_parsed_records(tag):
    clear = load(tag)[1]
    rows = parse_quotes(clear, MAN[tag]['stocks'])
    declared = check_quote_count(clear, rows)
    assert declared == MAN[tag]['declared'] == len(rows) == len(MAN[tag]['stocks'])
    assert struct.unpack_from('<H', clear, 2)[0] == declared


@pytest.mark.parametrize('tag', POINTS)
def test_every_returned_key_is_whitelisted(tag):
    """请求集之外的键（占位行，如 600839）绝不能被当数据。"""
    rows = parse_quotes(load(tag)[1], MAN[tag]['stocks'])
    expected = {(m, c) for m, c in MAN[tag]['stocks']}
    assert {(r['market'], r['code']) for r in rows} == expected


def test_preopen_records_exist_with_zero_price():
    """C-1 反例固化：判停牌要看「有没有记录」，不是 price<=0。

    09:24:55 五只请求票全部收到记录，且**全部** price=0 / vol=0，而 bid1/ask1 已有真实价。
    也就是说把 price<=0 当停牌会把整个盘前市场误判成停牌。
    """
    tag = '09_24_55_092455_001'
    rows = parse_quotes(load(tag)[1], MAN[tag]['stocks'])
    assert len(rows) == 5
    assert [r['price'] for r in rows] == [0.0] * 5
    assert [r['vol'] for r in rows] == [0] * 5
    assert all(r['bid1'] > 0 for r in rows)


@pytest.mark.parametrize('tag', POINTS)
def test_recv_replays_real_frame_from_stream(tag):
    resp, clear = load(tag)
    hdr, body = _recv(Stream(resp))
    assert hdr == resp[:16]
    assert body == clear


def test_short_stream_fails_closed():
    with pytest.raises(ConnectionError):
        _recv(Stream(load('09_24_55_092455_001')[0][:-1]))


def test_packed_larger_than_stream_fails_closed():
    resp = bytearray(load('09_24_55_092455_001')[0])
    struct.pack_into('<H', resp, 12, struct.unpack_from('<H', resp, 12)[0] + 1)
    with pytest.raises(ConnectionError):
        _recv(Stream(bytes(resp)))


def test_exact_reports_byte_counts():
    with pytest.raises(ConnectionError, match=r'got 3 of 5 bytes'):
        _exact(Stream(b'abc'), 5)


@pytest.mark.parametrize('delta', [1, -1, None])
def test_raw_len_mismatch_fails_closed(delta):
    resp, _ = load('09_30_06_093006_000')
    packed, raw = struct.unpack_from('<HH', resp, 12)
    bad_raw = 0 if delta is None else raw + delta
    with pytest.raises(ValueError):
        _unwrap_frame(resp[16:], packed, bad_raw)


def test_zlib_trailing_bytes_fail_closed():
    resp = load('09_30_06_093006_000')[0]
    packed, raw = struct.unpack_from('<HH', resp, 12)
    with pytest.raises(ValueError):
        _unwrap_frame(resp[16:] + b'\0' * 4, packed + 4, raw)


def test_truncated_compressed_stream_fails_closed():
    resp = load('09_30_06_093006_000')[0]
    packed, raw = struct.unpack_from('<HH', resp, 12)
    with pytest.raises(ValueError):
        _unwrap_frame(resp[16:packed - 6], packed - 6, raw)


@pytest.mark.parametrize('tag', POINTS)
def test_count_shortfall_fails_closed(tag):
    clear = load(tag)[1]
    rows = parse_quotes(clear, MAN[tag]['stocks'])
    with pytest.raises(ValueError, match='shortfall'):
        check_quote_count(clear, rows[:-1])


def test_over_declared_count_is_not_fatal():
    """解析条数多于声明数属冗余，不抛错（D8 注）。"""
    clear = bytearray(load('09_30_06_093006_000')[1])
    struct.pack_into('<H', clear, 2, 3)
    rows = parse_quotes(bytes(clear), MAN['09_30_06_093006_000']['stocks'])
    assert check_quote_count(bytes(clear), rows) == 3


def test_tampered_declared_count_fails_closed():
    """声明数被抬高时，解码器或闸门必须有一环报错，绝不静默通过。"""
    clear = bytearray(load('09_30_06_093006_000')[1])
    struct.pack_into('<H', clear, 2, 99)
    with pytest.raises((ValueError, struct.error)):
        check_quote_count(bytes(clear), parse_quotes(bytes(clear), MAN['09_30_06_093006_000']['stocks']))


def test_count_gate_tolerates_absent_body():
    assert check_quote_count(None, []) is None
    assert check_quote_count(b'\x01', []) is None