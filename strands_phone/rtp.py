"""RTP with G.711 u-law (PCMU), 20 ms frames at 8 kHz."""

from __future__ import annotations

import asyncio
import random
import struct
from typing import Protocol

from .config import FRAME
from .g711 import lin2ulaw, ulaw2lin


class AudioHandler(Protocol):
    def on_audio(self, pcm: bytes) -> None: ...


class Rtp(asyncio.DatagramProtocol):
    def __init__(self, call: AudioHandler):
        self.call = call
        self.transport: asyncio.DatagramTransport | None = None
        self.seq = random.randint(0, 65535)
        self.ts = random.randint(0, 2**31)
        self.ssrc = random.randint(0, 2**32 - 1)
        self.first = True

    def connection_made(self, transport):  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data, addr):  # type: ignore[override]
        if len(data) < 12 or data[0] >> 6 != 2:
            return
        cc, ext, pt = data[0] & 0x0F, data[0] & 0x10, data[1] & 0x7F
        off = 12 + 4 * cc
        if ext and len(data) >= off + 4:
            off += 4 + 4 * struct.unpack("!H", data[off + 2 : off + 4])[0]
        if pt == 0:
            self.call.on_audio(ulaw2lin(data[off:]))

    def send(self, pcm: bytes, addr) -> None:
        hdr = struct.pack("!BBHII", 0x80, (0x80 if self.first else 0) | 0, self.seq, self.ts, self.ssrc)
        self.first = False
        self.seq = (self.seq + 1) & 0xFFFF
        self.ts = (self.ts + FRAME) & 0xFFFFFFFF
        if self.transport:
            self.transport.sendto(hdr + lin2ulaw(pcm), addr)
