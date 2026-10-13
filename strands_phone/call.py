"""One phone call: outbound (we are the SIP UAC) or inbound (UAS), bridged to a BidiAgent.

Every call leaves calls/<utc>.wav (left = the other party, right = the agent) and calls/<utc>.json."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import signal
import struct
import time
import uuid
import wave
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from strands.bidi.types.media import AudioDelta

from .config import CALLER_ID, FRAME, MAX_CALL_S, PUBLIC_IP, RTP_PORT, SIP_PORT, VC_HOST
from .resample import Down3, Up3
from .rtp import Rtp
from .sip import Sip, _tag, allowed_networks, parse_sip, sdp_target

if TYPE_CHECKING:
    from strands.bidi import BidiAgent

log = logging.getLogger("strands_phone")
AgentFactory = Callable[..., Any]
GREET_OUTBOUND = "[The person you called just picked up the phone. Greet them now, in one short sentence.]"
GREET_INBOUND = (
    "[Your phone rang and you just picked up. The caller's number is {caller}. Greet them in one short sentence.]"
)


def _input_rate(agent: Any) -> int:
    """The sample rate the model wants in: 8000 (Nova, native) or 24000 (OpenAI Realtime, resampled)."""
    model = getattr(agent, "model", None)
    if model is not None and hasattr(model, "get_audio_config"):
        return int(model.get_audio_config()["input"]["sample_rate"])
    return 8000


class Call:
    def __init__(
        self,
        to: str,
        *,
        agent_factory: AgentFactory | None = None,
        vc_host: str = VC_HOST,
        vc_port: int = 5060,
        caller_id: str = CALLER_ID,
        public_ip: str = PUBLIC_IP,
        sip_port: int = SIP_PORT,
        rtp_port: int = RTP_PORT,
        calls_dir: str = "calls",
        record: bool | None = None,
        sip_allow: str | None = None,
    ):
        # Recording is opt-in: some places require every party's consent to record a call.
        self.record = os.environ.get("RECORD_CALLS", "").lower() in ("1", "true", "yes") if record is None else record
        self.sip_allow = allowed_networks(sip_allow)
        if agent_factory is None:
            from .agent import make_agent as agent_factory
        self.agent_factory = agent_factory
        self.up, self.down, self.model_rate = Up3(), Down3(), 8000
        self.vc_host, self.vc_port, self.caller_id, self.public_ip = vc_host, vc_port, caller_id, public_ip
        self.sip_port, self.rtp_port, self.calls_dir = sip_port, rtp_port, calls_dir
        self.to = to
        self.call_id = f"{uuid.uuid4().hex}@{self.public_ip}"
        self.from_tag = _tag()
        self.to_hdr = f"<sip:{to}@{self.vc_host}>"
        self.req_uri = f"sip:{to}@{self.vc_host}"
        self.proxy: tuple[str, int] | None = None
        self.remote_media: tuple[str, int] | None = None
        self.routes: list[str] = []
        self.answered = asyncio.Event()
        self.ended = asyncio.Event()
        self.end_reason = ""
        self.provisional = asyncio.Event()
        self.agent: BidiAgent | None = None
        self.loop = asyncio.get_running_loop()
        self.out = bytearray()  # agent PCM waiting to be played
        self.rx = bytearray()  # callee PCM since the last tick (recording)
        self.left: list[bytes] = []
        self.right: list[bytes] = []
        self.events: list[dict] = []
        self.t0 = time.monotonic()
        self.hangup_after_audio = False
        self.live = False
        self.last_agent_audio = 0.0

    # timeline
    def mark(self, kind: str, **kw) -> None:
        e = {"ms": int((time.monotonic() - self.t0) * 1000), "kind": kind, **kw}
        self.events.append(e)
        log.info("%6d ms %s %s", e["ms"], kind, " ".join(f"{k}={v}" for k, v in kw.items()))

    def via(self, branch: str) -> str:
        return f"SIP/2.0/UDP {self.public_ip}:{self.sip_port};branch=z9hG4bK{branch};rport"

    def sdp(self) -> str:
        return (
            "v=0\r\n"
            f"o=strands {int(time.time())} 1 IN IP4 {self.public_ip}\r\n"
            "s=strands-phone\r\n"
            f"c=IN IP4 {self.public_ip}\r\n"
            "t=0 0\r\n"
            f"m=audio {self.rtp_port} RTP/AVP 0 101\r\n"
            "a=rtpmap:0 PCMU/8000\r\n"
            "a=rtpmap:101 telephone-event/8000\r\n"
            "a=fmtp:101 0-16\r\n"
            "a=ptime:20\r\n"
            "a=sendrecv\r\n"
        )

    def request(
        self, method: str, cseq: int, branch: str, body: str = "", to_tag: str | None = None, uri: str | None = None
    ) -> str:
        to = self.to_hdr + (f";tag={to_tag}" if to_tag else "")
        lines = [
            f"{method} {uri or self.req_uri} SIP/2.0",
            f"Via: {self.via(branch)}",
            "Max-Forwards: 70",
            *[f"Route: {r}" for r in self.routes],
            f"From: <sip:{self.caller_id}@{self.public_ip}>;tag={self.from_tag}",
            f"To: {to}",
            f"Call-ID: {self.call_id}",
            f"CSeq: {cseq} {method}",
            f"Contact: <sip:{self.caller_id}@{self.public_ip}:{self.sip_port}>",
            "User-Agent: strands-phone",
        ]
        if body:
            lines += ["Content-Type: application/sdp"]
        lines += [f"Content-Length: {len(body.encode())}", "", body]
        return "\r\n".join(lines)

    # ---- SIP in
    def on_sip(self, data: bytes, addr) -> None:
        start, h, body = parse_sip(data)
        log.debug("SIP <<< %s", start)
        if start.startswith("SIP/2.0"):
            code = int(start.split()[1])
            cseq = h.get("cseq", ["0 X"])[0]
            if "INVITE" not in cseq:
                return  # BYE response etc.
            if code < 200:
                if not self.provisional.is_set():
                    self.mark("sip", code=code)
                self.provisional.set()
                if body and (t := sdp_target(body)):
                    self.remote_media = t
                return
            to = h.get("to", [""])[0]
            self.to_tag = to.split("tag=")[1].split(";")[0] if "tag=" in to else None
            if 200 <= code < 300:
                if body and (t := sdp_target(body)):
                    self.remote_media = t
                self.remote_contact = h.get("contact", [f"<{self.req_uri}>"])[0].strip("<>").split(">")[0]
                self.routes = list(reversed(h.get("record-route", [])))
                ack = self.request("ACK", 1, _tag(), to_tag=self.to_tag, uri=self.remote_contact)
                self.sip.send(ack, addr)
                if not self.answered.is_set():
                    self.mark("answered", media=f"{self.remote_media}")
                    self.answered.set()
            else:
                # non-2xx final: ACK on the INVITE's branch
                ack = self.request("ACK", 1, self.invite_branch, to_tag=self.to_tag)
                self.sip.send(ack, addr)
                self.finish(f"sip {code} {start.split(' ', 2)[-1]}")
            return
        method = start.split()[0]
        resp = "\r\n".join(
            [
                "SIP/2.0 200 OK",
                *[f"Via: {v}" for v in h.get("via", [])],
                f"From: {h['from'][0]}",
                f"To: {h['to'][0]}",
                f"Call-ID: {h['call-id'][0]}",
                f"CSeq: {h['cseq'][0]}",
                "Content-Length: 0",
                "",
                "",
            ]
        )
        self.sip.send(resp, addr)
        if method == "BYE":
            self.finish("callee hung up")

    def finish(self, reason: str) -> None:
        if not self.ended.is_set():
            self.end_reason = reason
            self.mark("ended", reason=reason)
            self.ended.set()

    # ---- media in
    def on_audio(self, pcm: bytes) -> None:
        self.rx += pcm
        if self.live and not self.ended.is_set():
            if self.model_rate == 24000:
                pcm = self.up(pcm)
            self.loop.create_task(self.agent.send(AudioDelta(format="pcm", source={"bytes": pcm})))

    # ---- run
    async def run(self) -> None:
        loop = self.loop
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.finish, "operator hung up")
        _, self.sip = await loop.create_datagram_endpoint(
            lambda: Sip(self, self.sip_allow), local_addr=("0.0.0.0", self.sip_port)
        )
        _, self.rtp = await loop.create_datagram_endpoint(lambda: Rtp(self), local_addr=("0.0.0.0", self.rtp_port))
        infos = await loop.getaddrinfo(self.vc_host, self.vc_port, type=2)
        self.proxy = infos[0][4][:2]
        self.mark("dialing", to=self.to, via=f"{self.vc_host} ({self.proxy[0]})", caller_id=self.caller_id)

        tick = loop.create_task(self.clock())
        # INVITE with UDP retransmission until a provisional arrives (RFC 3261 timer A)
        self.invite_branch = _tag()
        invite = self.request("INVITE", 1, self.invite_branch, body=self.sdp())
        wait = 0.5
        for _ in range(7):
            self.sip.send(invite, self.proxy)
            try:
                await asyncio.wait_for(self.provisional.wait(), wait)
                break
            except TimeoutError:
                wait = min(wait * 2, 4)
        else:
            self.finish("no SIP response from the voice connector")
        done = loop.create_task(self.ended.wait())
        ans = loop.create_task(self.answered.wait())
        await asyncio.wait({done, ans}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
        if self.answered.is_set() and not self.ended.is_set():
            # The model connection opens on answer, so a ringing phone never idles a Nova stream.
            self.agent = self.agent_factory(self)
            self.model_rate = _input_rate(self.agent)
            self.mark("model", id=getattr(getattr(self.agent, "model", None), "model_id", "stub"), rate=self.model_rate)
            async with self.agent:
                self.live = True
                self.mark("agent_started")
                recv = loop.create_task(self.pump())
                await self.agent.send(GREET_OUTBOUND)
                try:
                    await asyncio.wait_for(self.ended.wait(), MAX_CALL_S)
                except TimeoutError:
                    self.finish("max call length")
                recv.cancel()
        elif not self.ended.is_set():
            self.finish("no answer in 60 s")
        if self.answered.is_set() and self.end_reason != "callee hung up":
            self.sip.send(self.request("BYE", 2, _tag(), to_tag=self.to_tag, uri=self.remote_contact), self.proxy)
            await asyncio.sleep(0.5)
        tick.cancel()
        self.save()

    async def clock(self) -> None:
        """20 ms playout clock: agent audio when there is some, else a -60 dBFS noise floor."""
        nxt = time.monotonic()
        nbytes = FRAME * 2
        while True:
            nxt += 0.02
            if len(self.out) >= nbytes:
                frame = bytes(self.out[:nbytes])
                del self.out[:nbytes]
            else:
                frame = struct.pack(f"<{FRAME}h", *(random.randint(-30, 30) for _ in range(FRAME)))
                # hang up only once the goodbye has been generated AND played: 1.2 s with no new agent audio
                if self.hangup_after_audio and not self.out and time.monotonic() - self.last_agent_audio > 1.2:
                    self.hangup_after_audio = False
                    self.finish("agent hung up")
            if self.remote_media:
                self.rtp.send(frame, self.remote_media)
            if self.answered.is_set():
                rx = bytes(self.rx[:nbytes]).ljust(nbytes, b"\0")
                del self.rx[: len(self.rx)]
                self.left.append(rx)
                self.right.append(frame)
            else:
                self.rx.clear()
            await asyncio.sleep(max(0, nxt - time.monotonic()))

    async def pump(self) -> None:
        assert self.agent
        speaking = False
        async for ev in self.agent.receive():
            t = ev.get("type")
            if t == "bidi_audio_delta":
                if not speaking:
                    speaking = True
                    self.mark("agent_audio_start")
                audio = base64.b64decode(ev["audio"])
                rate = ev.get("sample_rate", 8000)
                if rate == 24000:
                    audio = self.down(audio)
                elif rate != 8000:
                    raise ValueError(f"unsupported model output rate {rate}")
                self.out += audio
                self.last_agent_audio = time.monotonic()
            elif t == "bidi_audio_stop":
                speaking = False
            elif t == "bidi_barge_in":
                dropped = len(self.out) // 16
                self.out.clear()
                speaking = False
                self.mark("barge_in", dropped_ms=dropped)
            elif t == "bidi_transcript_block":
                self.mark("transcript", role=ev["role"], text=repr(ev["transcript"]))
            elif t == "bidi_tool_use_blocks":
                self.mark("tool_use", tools=[u.get("name") for u in ev.get("tool_uses", [])])
            elif t == "bidi_connection_restart":
                self.mark("model_reconnect")

    def save(self) -> None:
        if not self.record:
            log.info(
                "call ended: %s (%.1f s, not recorded; RECORD_CALLS=1 to keep a WAV + timeline)",
                self.end_reason,
                len(self.left) * 0.02,
            )
            return
        os.makedirs(self.calls_dir, exist_ok=True)
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        with wave.open(f"{self.calls_dir}/{name}.wav", "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(8000)
            for left, right in zip(self.left, self.right):
                pairs = zip(struct.unpack(f"<{FRAME}h", left), struct.unpack(f"<{FRAME}h", right))
                w.writeframes(b"".join(struct.pack("<hh", a, b) for a, b in pairs))
        with open(f"{self.calls_dir}/{name}.json", "w") as f:
            json.dump(
                {"to": self.to, "call_id": self.call_id, "reason": self.end_reason, "events": self.events}, f, indent=2
            )
        log.info("saved %s/%s.wav (%.1f s) + .json", self.calls_dir, name, len(self.left) * 0.02)


class InboundCall(Call):
    """UAS side: the Voice Connector sends us an INVITE when someone dials self.caller_id."""

    def __init__(self, **kw: Any):
        super().__init__(to="caller", **kw)
        self.invite: tuple[dict[str, list[str]], tuple] | None = None
        self.got_invite = asyncio.Event()
        self.acked = asyncio.Event()
        self.local_tag = _tag()
        self.cseq = 100

    def reply(self, code: str, h: dict[str, list[str]], addr, body: str = "", tag: bool = True) -> None:
        to = h["to"][0] + (f";tag={self.local_tag}" if tag and "tag=" not in h["to"][0] else "")
        lines = [
            "SIP/2.0 " + code,
            *[f"Via: {v}" for v in h.get("via", [])],
            *[f"Record-Route: {r}" for r in h.get("record-route", [])],
            f"From: {h['from'][0]}",
            f"To: {to}",
            f"Call-ID: {h['call-id'][0]}",
            f"CSeq: {h['cseq'][0]}",
            f"Contact: <sip:{self.caller_id}@{self.public_ip}:{self.sip_port}>",
            "User-Agent: strands-phone",
        ]
        if body:
            lines.append("Content-Type: application/sdp")
        lines += [f"Content-Length: {len(body.encode())}", "", body]
        self.sip.send("\r\n".join(lines), addr)

    def on_sip(self, data: bytes, addr) -> None:
        start, h, body = parse_sip(data)
        if start.startswith("SIP/2.0"):
            return
        method = start.split()[0]
        if method == "INVITE":
            if self.invite and h["call-id"][0] != self.invite[0]["call-id"][0]:
                self.reply("486 Busy Here", h, addr)
                return
            first = self.invite is None
            self.invite = (h, addr)
            self.call_id = h["call-id"][0]
            self.reply("100 Trying", h, addr, tag=False)
            if body and (t := sdp_target(body)):
                self.remote_media = t
            if first:
                self.caller = h["from"][0].split("sip:")[1].split("@")[0] if "sip:" in h["from"][0] else "?"
                self.mark("ringing", caller=self.caller, media=f"{self.remote_media}")
                self.got_invite.set()
            elif self.answered.is_set():
                self.reply("200 OK", h, addr, body=self.sdp())  # retransmitted INVITE after our 200
        elif method == "ACK":
            self.acked.set()
        elif method in ("BYE", "CANCEL"):
            self.reply("200 OK", h, addr)
            if method == "CANCEL" and self.invite:
                self.reply("487 Request Terminated", *self.invite)
            self.finish("caller hung up")
        else:
            self.reply("200 OK", h, addr)

    def bye(self) -> None:
        h, addr = self.invite  # type: ignore[misc]
        self.cseq += 1
        contact = h.get("contact", [h["from"][0]])[0].split("<")[-1].split(">")[0]
        to_local = h["to"][0] + ("" if "tag=" in h["to"][0] else f";tag={self.local_tag}")
        msg = "\r\n".join(
            [
                f"BYE {contact} SIP/2.0",
                f"Via: {self.via(_tag())}",
                "Max-Forwards: 70",
                *[f"Route: {r}" for r in h.get("record-route", [])],
                f"From: {to_local}",
                f"To: {h['from'][0]}",
                f"Call-ID: {h['call-id'][0]}",
                f"CSeq: {self.cseq} BYE",
                "Content-Length: 0",
                "",
                "",
            ]
        )
        self.sip.send(msg, addr)

    async def run(self) -> None:  # type: ignore[override]
        loop = self.loop

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.finish, "operator stopped")
        _, self.sip = await loop.create_datagram_endpoint(
            lambda: Sip(self, self.sip_allow), local_addr=("0.0.0.0", self.sip_port)
        )
        _, self.rtp = await loop.create_datagram_endpoint(lambda: Rtp(self), local_addr=("0.0.0.0", self.rtp_port))
        self.mark("listening", number=self.caller_id)
        stop = loop.create_task(self.ended.wait())
        inv = loop.create_task(self.got_invite.wait())
        await asyncio.wait({stop, inv}, return_when=asyncio.FIRST_COMPLETED)
        if self.ended.is_set():
            return
        self.t0 = time.monotonic()
        self.events.clear()
        self.mark("ringing", caller=self.caller)
        tick = loop.create_task(self.clock())
        h, addr = self.invite  # type: ignore[misc]
        self.reply("180 Ringing", h, addr)
        self.agent = self.agent_factory(self, inbound=True)
        self.model_rate = _input_rate(self.agent)
        self.mark("model", id=getattr(getattr(self.agent, "model", None), "model_id", "stub"), rate=self.model_rate)
        async with self.agent:  # open the model while it "rings", then pick up
            self.answered.set()
            for i in range(7):
                self.reply("200 OK", h, addr, body=self.sdp())
                try:
                    await asyncio.wait_for(self.acked.wait(), 0.5 * 2**i)
                    break
                except TimeoutError:
                    pass
            self.live = True
            self.mark("answered")
            recv = loop.create_task(self.pump())
            await self.agent.send(GREET_INBOUND.format(caller=self.caller))
            try:
                await asyncio.wait_for(self.ended.wait(), MAX_CALL_S)
            except TimeoutError:
                self.finish("max call length")
            recv.cancel()
        if self.end_reason != "caller hung up":
            self.bye()
            await asyncio.sleep(0.5)
        tick.cancel()
        self.save()
