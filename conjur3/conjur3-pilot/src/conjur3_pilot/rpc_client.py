"""XML-RPC client for the Conjur3 addon. Reconnects transparently on stale sockets."""

from __future__ import annotations

import socket
import xmlrpc.client
from typing import Any

from .seat_context import current_seat


class _SeatTransport(xmlrpc.client.Transport):
    """Inject the current seat as an HTTP header so the relay can route the call
    to the right customer's FreeCAD. No-op when there's no seat (local mode)."""

    def send_headers(self, connection, headers):  # type: ignore[override]
        seat = current_seat.get(None)
        if seat:
            connection.putheader("X-Conjur3-Seat", seat)
        super().send_headers(connection, headers)


class PilotClient:
    def __init__(self, host: str = "localhost", port: int = 9875, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._proxy: xmlrpc.client.ServerProxy | None = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _connect(self) -> xmlrpc.client.ServerProxy:
        socket.setdefaulttimeout(self.timeout)
        self._proxy = xmlrpc.client.ServerProxy(
            self.endpoint, allow_none=True, transport=_SeatTransport()
        )
        return self._proxy

    def ping(self) -> bool:
        try:
            res = self._call("ping")
            return bool(res and res.get("success"))
        except Exception:
            return False

    def disconnect(self):
        self._proxy = None

    def _call(self, method: str, *args: Any) -> Any:
        if self._proxy is None:
            self._connect()
        try:
            return getattr(self._proxy, method)(*args)
        except (ConnectionError, OSError, xmlrpc.client.ProtocolError):
            # Reconnect once and retry.
            self._connect()
            return getattr(self._proxy, method)(*args)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            if kwargs:
                # XML-RPC is positional-only; merge kwargs as a trailing dict so handlers
                # can still read them via `.get(...)`. Handlers that expect positional
                # args beyond the caller-supplied ones will see the dict as the next arg.
                return self._call(name, *args, kwargs)
            return self._call(name, *args)

        return call
