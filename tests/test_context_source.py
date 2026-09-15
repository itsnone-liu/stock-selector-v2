"""context_source 自动拉取 + capital-observer 契约测试。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from stock_selector.decision.context_source import (
    context_available_at,
    context_freshness,
    fetch_context_payload,
)
from stock_selector.decision.regime import parse_capital_context

PAYLOAD = {
    "sector_id": "BK0420",
    "symbol": "600519",
    "as_of": "2026-09-14",
    "context": "divergent",
    "channels": {
        "em_board_flow": {"evidence_type": "proxy", "observation_date": "2026-09-15",
                          "available_at": "2026-09-15", "status": "fresh",
                          "direction": "outflow"},
        "market_margin": {"evidence_type": "fact", "observation_date": "2026-09-14",
                          "available_at": "2026-09-14", "status": "fresh",
                          "direction": "inflow"},
        "broad_etf_shares": {"evidence_type": "fact", "observation_date": "2026-09-14",
                             "available_at": "2026-09-14", "status": "fresh",
                             "direction": "inflow",
                             "note": "T-1官方份额事实"},
    },
    "method_version": "context-v0.1-rule",
    "limitations": [],
}


def _serve(handler_cls) -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}", server


class _OK(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps(PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


class _Broken(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_fetch_and_parse_roundtrip():
    base, server = _serve(_OK)
    try:
        payload = fetch_context_payload("600519", board="BK0420", base_url=base)
        assert payload is not None
        parsed = parse_capital_context(payload)
        assert parsed.context == "divergent"
        assert parsed.sector_id == "BK0420"
        assert set(parsed.channels) == {"em_board_flow", "market_margin", "broad_etf_shares"}
        assert parsed.channels["em_board_flow"].evidence_type == "proxy"
        assert parsed.channels["market_margin"].evidence_type == "fact"
        assert parsed.limitations == []
        assert context_available_at(payload) == "2026-09-15"
    finally:
        server.shutdown()


def test_fetch_failure_returns_none_not_crash():
    base, server = _serve(_Broken)
    try:
        assert fetch_context_payload("600519", base_url=base) is None
    finally:
        server.shutdown()
    # 端口关掉后（连接拒绝）也返回 None
    assert fetch_context_payload("600519", base_url=base) is None


def test_parse_unknown_on_none():
    parsed = parse_capital_context(None)
    assert parsed.context == "unknown"
    assert "capital_context_unavailable" in parsed.limitations


def test_freshness_buckets():
    assert context_freshness(PAYLOAD, datetime(2026, 9, 15, 15, 5)) == "current"
    assert context_freshness(PAYLOAD, datetime(2026, 9, 18, 15, 5)) == "t_minus_few"
    assert context_freshness(PAYLOAD, datetime(2026, 10, 1, 15, 5)) == "stale"
    assert context_freshness(None, datetime(2026, 9, 15)) == "unknown"
