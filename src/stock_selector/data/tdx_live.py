"""Pure-stdlib TDX 7709 market bars client.

The client implements the op11 data-session handshake and op052d count-based
bars request.  It deliberately exposes raw, unadjusted market bars only.
Prices/amount are yuan; volume is normalized to shares for every frequency.
"""
from __future__ import annotations

import secrets
import socket
import struct
import time
import zlib
from dataclasses import dataclass
from importlib.resources import files

DEFAULT_SERVERS = (
    ("123.60.73.44", 7709), ("123.60.84.66", 7709),
    ("123.60.70.228", 7709), ("124.70.133.119", 7709),
    ("124.71.187.72", 7709), ("124.71.187.122", 7709),
    ("121.36.225.169", 7709), ("110.41.147.114", 7709),
)
CATEGORY = {"1m": 8, "5m": 0, "daily": 9}
MAX_PER_CALL = 800


@dataclass(frozen=True)
class TdxBar:
    time_key: str
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int


def market_of(code: str) -> int:
    code = str(code).zfill(6)
    if code.startswith(("4", "8", "920")):
        raise ValueError("TDX 7709 BJ market is unsupported")
    return 1 if code.startswith(("5", "6", "9")) else 0


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise ConnectionError(f"TDX peer closed ({len(out)}/{n})")
        out.extend(chunk)
    return bytes(out)


def _recv_response(sock: socket.socket) -> tuple[bytes, bytes]:
    header = _recv_exact(sock, 16)
    compressed_len = struct.unpack_from("<H", header, 12)[0]
    payload = _recv_exact(sock, compressed_len)
    try:
        body = zlib.decompress(payload) if payload[:1] == b"\x78" else payload
    except zlib.error:
        body = payload
    return header, body


def _request(seq: int, market: int, code: str, category: int,
             start: int, count: int) -> bytes:
    return struct.pack(
        "<HIHHHH6sHHHHIIH", 0x10C, 0x01016408, 0x1C, 0x1C,
        0x052D, market, code.encode("ascii"), category, 1,
        start, count, 0, 0, 0,
    )


def _price(buf: bytes, pos: int) -> tuple[int, int]:
    byte = buf[pos]
    value = byte & 0x3F
    negative = bool(byte & 0x40)
    shift = 6
    while byte & 0x80:
        pos += 1
        byte = buf[pos]
        value += (byte & 0x7F) << shift
        shift += 7
    return (-value if negative else value), pos + 1


def _datetime(category: int, buf: bytes, pos: int) -> tuple[str, int]:
    if category < 4 or category in (7, 8):
        packed_day, minutes = struct.unpack_from("<HH", buf, pos)
        year = (packed_day >> 11) + 2004
        month = (packed_day % 2048) // 100
        day = (packed_day % 2048) % 100
        return (f"{year:04d}{month:02d}{day:02d}{minutes // 60:02d}{minutes % 60:02d}", pos + 4)
    packed_day = struct.unpack_from("<I", buf, pos)[0]
    return f"{packed_day:08d}", pos + 4


def parse_bars(body: bytes, category: int) -> list[TdxBar]:
    if len(body) < 2:
        return []
    count = struct.unpack_from("<H", body, 0)[0]
    pos, previous_close = 2, 0
    result: list[TdxBar] = []
    for _ in range(count):
        try:
            key, pos = _datetime(category, body, pos)
            d_open, pos = _price(body, pos)
            d_close, pos = _price(body, pos)
            d_high, pos = _price(body, pos)
            d_low, pos = _price(body, pos)
            volume, amount = struct.unpack_from("<ff", body, pos)
            pos += 8
        except (IndexError, struct.error):
            raise ValueError("truncated TDX op052d response")
        base = previous_close + d_open
        previous_close = base + d_close
        result.append(TdxBar(
            key, round(base / 1000, 3), round((base + d_high) / 1000, 3),
            round((base + d_low) / 1000, 3), round(previous_close / 1000, 3),
            float(amount), int(round(volume)) * (100 if category == 9 else 1),
        ))
    return result


class TdxLiveClient:
    """One persistent TDX session; caller closes it or uses a context manager."""

    def __init__(self, host: str | None = None, port: int = 7709,
                 timeout: float = 15.0):
        self.host, self.port = host or self.select_server(timeout=2.0), port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.seq = 0
        self._connect()

    @staticmethod
    def select_server(timeout: float = 2.0) -> str:
        errors = []
        for host, port in DEFAULT_SERVERS:
            try:
                sock = socket.create_connection((host, port), timeout=timeout)
                sock.close()
                return host
            except OSError as exc:
                errors.append(f"{host}:{type(exc).__name__}")
        raise ConnectionError("no reachable TDX server: " + ", ".join(errors))

    def _connect(self) -> None:
        template = files("stock_selector.data").joinpath("assets/op11_template.bin").read_bytes()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self.sock.sendall(template + secrets.token_bytes(8))
        header, _ = _recv_response(self.sock)
        if struct.unpack_from("<H", header, 10)[0] != 0x000B:
            self.close()
            raise RuntimeError("TDX op11 session rejected")

    def fetch(self, code: str, period: str, start: int = 0,
              count: int = MAX_PER_CALL) -> list[TdxBar]:
        if period not in CATEGORY:
            raise ValueError(f"unsupported period: {period}")
        if not 1 <= count <= MAX_PER_CALL:
            raise ValueError(f"count must be 1..{MAX_PER_CALL}")
        code = str(code).split(".")[-1].zfill(6)
        for attempt in range(3):
            try:
                if self.sock is None:
                    self._connect()
                self.seq = (self.seq + 1) & 0xFF or 1
                assert self.sock is not None
                self.sock.sendall(_request(self.seq, market_of(code), code,
                                           CATEGORY[period], start, count))
                _, body = _recv_response(self.sock)
                return parse_bars(body, CATEGORY[period])
            except (OSError, ConnectionError, RuntimeError):
                self.close()
                if attempt == 2:
                    raise
                time.sleep(0.25 * (attempt + 1))
        return []

    def fetch_range(self, code: str, period: str, max_bars: int = 10000,
                    since: str | None = None) -> list[TdxBar]:
        bars: dict[str, TdxBar] = {}
        start = 0
        while len(bars) < max_bars:
            page = self.fetch(code, period, start, min(MAX_PER_CALL, max_bars - len(bars)))
            if not page:
                break
            for bar in page:
                bars[bar.time_key] = bar
            if since and min(b.time_key[:8] for b in page) <= since.replace("-", ""):
                break
            if len(page) < MAX_PER_CALL:
                break
            start += len(page)
        return sorted(bars.values(), key=lambda b: b.time_key)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def __enter__(self) -> "TdxLiveClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
