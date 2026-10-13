"""Just enough SIP over UDP for one call to or from a Chime SDK Voice Connector."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import uuid
from typing import Protocol

log = logging.getLogger("strands_phone.sip")


class SipHandler(Protocol):
    def on_sip(self, data: bytes, addr: tuple) -> None: ...


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def parse_sip(data: bytes) -> tuple[str, dict[str, list[str]], str]:
    head, _, body = data.decode(errors="replace").partition("\r\n\r\n")
    lines = head.split("\r\n")
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    return lines[0], headers, body


def sdp_target(body: str) -> tuple[str, int] | None:
    ip = port = None
    for line in body.splitlines():
        if line.startswith("c=IN IP4 "):
            ip = line.split()[-1]
        elif line.startswith("m=audio "):
            port = int(line.split()[1])
    return (ip, port) if ip and port else None


class Sip(asyncio.DatagramProtocol):
    def connection_made(self, transport):  # type: ignore[override]
        self.transport = transport

    def __init__(self, call: SipHandler, allow: list[ipaddress.IPv4Network] | None = None):
        self.call = call
        self.allow = allow or []
        self.transport: asyncio.DatagramTransport | None = None

    def datagram_received(self, data, addr):  # type: ignore[override]
        if data.strip() == b"":
            return  # keepalive
        if self.allow and not any(ipaddress.ip_address(addr[0]) in net for net in self.allow):
            log.warning("dropped SIP from %s: not in SIP_ALLOW", addr[0])
            return
        try:
            self.call.on_sip(data, addr)
        except Exception:  # a malformed packet must never take the call down
            log.exception("dropped malformed SIP from %s", addr[0])

    def send(self, msg: str, addr) -> None:
        log.debug("SIP >>> %s", msg.split("\r\n", 1)[0])
        assert self.transport
        self.transport.sendto(msg.encode(), addr)


def allowed_networks(spec: str | None = None) -> list[ipaddress.IPv4Network]:
    """SIP_ALLOW="3.80.16.0/23,52.55.62.128/25": only accept SIP from these sources (empty: accept all)."""
    spec = os.environ.get("SIP_ALLOW", "") if spec is None else spec
    return [ipaddress.ip_network(c.strip()) for c in spec.split(",") if c.strip()]
