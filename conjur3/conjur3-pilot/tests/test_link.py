"""Verify the in-addon Conjur3 link (pure-Python connector).

We don't stand up a real relay here; we exercise the no-key guard and the
local-RPC forwarding path (which is what bridges relay → FreeCAD), plus confirm
the vendored websocket-client imports. The full WS round-trip is validated live
against the deployed relay.
"""
import http.server
import os
import sys
import threading
from pathlib import Path

ADDON = Path(__file__).resolve().parents[1] / "addon" / "conjur3_pilot"
sys.path.insert(0, str(ADDON))

import conjur3_link as link  # noqa: E402


def test_vendored_websocket_imports():
    import websocket  # vendored, pure-Python

    assert hasattr(websocket, "WebSocketApp")


def test_no_key_is_noop():
    msg = link.start_link({})
    assert "no seat key" in msg


def test_forward_posts_to_local_rpc():
    # A tiny stand-in for FreeCAD's XML-RPC server on 127.0.0.1.
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            seen["body"] = self.rfile.read(n).decode()
            seen["ctype"] = self.headers.get("content-type")
            self.send_response(200)
            self.send_header("content-type", "text/xml")
            self.end_headers()
            self.wfile.write(b"<methodResponse><ok/></methodResponse>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    local = "http://127.0.0.1:%d" % srv.server_address[1]

    status, ctype, data = link._forward(local, "/", {"content-type": "text/xml"}, "<ping/>")
    assert status == 200
    assert "methodResponse" in data
    assert seen["body"] == "<ping/>"
    assert seen["ctype"] == "text/xml"


def test_forward_unreachable_returns_502():
    status, ctype, data = link._forward("http://127.0.0.1:1", "/", {}, "x")
    assert status == 502
    assert "connector:" in data
