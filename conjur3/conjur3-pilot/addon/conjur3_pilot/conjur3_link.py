"""Conjur3 link — the connector, in-process inside FreeCAD.

Historically a separate Node.js process bridged the hosted relay to the local
FreeCAD RPC. That can't work under a strictly-confined FreeCAD (e.g. the snap),
which may not execute host binaries. So the bridge now lives *inside* the addon
as pure Python: a background thread runs a WebSocket client (vendored
websocket-client) that dials OUT to the relay, and forwards each request the
hosted MCP makes to this FreeCAD's own RPC server on 127.0.0.1:9875.

No Node, no extra process, no inbound ports — and it starts/stops with FreeCAD.
It contains no product logic; the MCP commands/code/knowledge stay on the server.

Wire protocol (must match mcp-gateway/src/relay.ts):
  connect:  GET {relay}/connector?key={seat key}        (401 close ⇒ bad key)
  recv:     {"t":"req","id":N,"path":"/","headers":{...},"body":"..."}
  send:     {"t":"res","id":N,"status":200,"headers":{"content-type":..},"body":..}
  close 4001 ⇒ superseded by a newer session for this seat → stop, don't retry.

Config comes from conjur3_settings.json (written by the installer):
  conjur3_key    — seat key (required)
  conjur3_relay  — e.g. wss://mcp.conjur3.com  (ws://… for local dev)
  conjur3_local  — defaults to http://127.0.0.1:9875 (this FreeCAD's RPC)
"""
import json
import os
import sys
import threading
import urllib.request

# Make the vendored, pure-Python websocket-client importable.
_VENDOR = os.path.join(os.path.dirname(__file__), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

try:
    import FreeCAD  # noqa: F401 — only for console logging when inside FreeCAD
except Exception:  # pragma: no cover - allows standalone testing
    FreeCAD = None

DEFAULT_RELAY = "wss://mcp.conjur3.com"
DEFAULT_LOCAL = "http://127.0.0.1:9875"

_thread = None
_ws = None
_stop = threading.Event()
_superseded = False
_registered = False


def _log(msg, warn=False):
    if FreeCAD is not None:
        (FreeCAD.Console.PrintWarning if warn else FreeCAD.Console.PrintMessage)(
            "[Conjur3] %s\n" % msg
        )
    else:  # pragma: no cover
        print("[Conjur3]", msg)


def _forward(local, path, headers, body):
    """POST the relayed request to this FreeCAD's local RPC; return (status, ctype, text)."""
    ctype = headers.get("content-type", "text/xml")
    req = urllib.request.Request(
        local + path,
        data=(body or "").encode("utf-8"),
        headers={"Content-Type": ctype},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read().decode("utf-8", "replace")
            rctype = resp.headers.get("content-type", "text/xml")
            return resp.status, rctype, data
    except urllib.error.HTTPError as e:  # RPC returned a non-2xx
        return e.code, "text/plain", e.read().decode("utf-8", "replace")
    except Exception as e:  # FreeCAD RPC down / unreachable
        return 502, "text/plain", "connector: %s" % e


def _run(key, relay, local):
    import websocket  # vendored

    url = "%s/connector?key=%s" % (relay, urllib.parse.quote(key, safe=""))
    backoff = 1.0
    global _ws, _superseded

    def on_open(ws):
        nonlocal backoff
        backoff = 1.0
        _log("link established → %s (forwarding to %s)" % (relay, local))

    def on_message(ws, raw):
        try:
            m = json.loads(raw)
        except Exception:
            return
        if m.get("t") != "req":
            return
        status, ctype, data = _forward(local, m.get("path", "/"), m.get("headers", {}), m.get("body", ""))
        try:
            ws.send(json.dumps(
                {"t": "res", "id": m.get("id"), "status": status,
                 "headers": {"content-type": ctype}, "body": data}
            ))
        except Exception as e:
            _log("reply failed: %s" % e, warn=True)

    def on_close(ws, code, _msg):
        global _superseded
        if code == 4001:
            _superseded = True
            _log("link superseded by a newer session — stopping.", warn=True)

    def on_error(ws, err):
        _log("link error: %s" % err, warn=True)

    while not _stop.is_set() and not _superseded:
        _ws = websocket.WebSocketApp(
            url, on_open=on_open, on_message=on_message,
            on_close=on_close, on_error=on_error,
        )
        try:
            _ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            _log("link crashed: %s" % e, warn=True)
        if _stop.is_set() or _superseded:
            break
        _stop.wait(backoff)  # reconnect with capped backoff
        backoff = min(backoff * 2, 15.0)


def start_link(settings):
    """Start the in-process link if a seat key is configured. Returns a status string."""
    global _thread, _superseded
    if _thread is not None and _thread.is_alive():
        return "Conjur3 link: already running."

    key = (settings.get("conjur3_key") or os.environ.get("CONJUR3_KEY") or "").strip()
    if not key:
        return "Conjur3 link: no seat key configured — skipped."

    relay = (settings.get("conjur3_relay") or os.environ.get("CONJUR3_RELAY") or DEFAULT_RELAY).rstrip("/")
    local = (settings.get("conjur3_local") or os.environ.get("CONJUR3_LOCAL") or DEFAULT_LOCAL).rstrip("/")

    _stop.clear()
    _superseded = False
    _thread = threading.Thread(target=_run, args=(key, relay, local), name="conjur3-link", daemon=True)
    _thread.start()
    return "Conjur3 link starting → %s" % relay


def stop_link():
    global _ws
    _stop.set()
    if _ws is not None:
        try:
            _ws.close()
        except Exception:
            pass
    _ws = None


def register_shutdown():
    """Ensure the link thread is torn down when FreeCAD exits."""
    global _registered
    if _registered:
        return
    _registered = True
    import atexit

    atexit.register(stop_link)
    try:
        from PySide import QtGui

        app = QtGui.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(stop_link)
    except Exception:
        pass


# urllib.parse / urllib.error are submodules — import lazily-safe at module load.
import urllib.parse  # noqa: E402
import urllib.error  # noqa: E402
