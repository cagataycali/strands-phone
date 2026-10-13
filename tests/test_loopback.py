"""A real SIP + RTP call on localhost: our UAC dials our UAS. Stub agents stand in for Nova Sonic."""

import asyncio
import base64
import json
import math
import struct
import time
import wave

from strands_phone import Call, InboundCall


class StubAgent:
    """Speaks a 440 Hz tone for `speak_s`, then (if `hang_up`) ends the call like the hang_up tool."""

    def __init__(self, call, speak_s=0.6, hang_up=False):
        self.call, self.speak_s, self.hang_up, self.sent = call, speak_s, hang_up, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def send(self, item):
        self.sent.append(item)

    async def receive(self):
        n = int(8000 * self.speak_s)
        tone = struct.pack(f"<{n}h", *(int(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(n)))
        yield {"type": "bidi_audio_delta", "audio": base64.b64encode(tone).decode(), "sample_rate": 8000}
        yield {"type": "bidi_transcript_block", "role": "assistant", "transcript": "beep"}
        if self.hang_up:
            self.call.hangup_after_audio = True
            self.call.last_agent_audio = time.monotonic()
        await asyncio.Event().wait()


def rms(path, channel):
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    s = struct.unpack(f"<{len(frames) // 2}h", frames)[channel::2]
    return math.sqrt(sum(x * x for x in s) / max(len(s), 1))


async def _call(tmp_path):
    common = dict(public_ip="127.0.0.1", caller_id="+15550000000", record=True)
    agents = {}

    def factory(name, **kw):
        def make(call, inbound=False):
            agents[name] = StubAgent(call, **kw)
            return agents[name]

        return make

    callee = InboundCall(
        agent_factory=factory("callee"), sip_port=15060, rtp_port=15070, calls_dir=str(tmp_path / "in"), **common
    )
    caller = Call(
        "+15551112222",
        agent_factory=factory("caller", speak_s=1.0, hang_up=True),
        vc_host="127.0.0.1",
        vc_port=15060,
        sip_port=15062,
        rtp_port=15072,
        calls_dir=str(tmp_path / "out"),
        **common,
    )
    await asyncio.wait_for(asyncio.gather(callee.run(), caller.run()), 20)
    return callee, caller, agents


def test_loopback_call(tmp_path):
    callee, caller, agents = asyncio.run(_call(tmp_path))
    assert caller.end_reason == "agent hung up"
    assert callee.end_reason == "caller hung up"  # our BYE reached the UAS
    assert any("picked up" in str(x) for x in agents["caller"].sent)  # greeting cue
    assert any("phone rang" in str(x) for x in agents["callee"].sent)
    # audio crossed both ways over RTP + G.711: each side's left channel holds the other's tone
    (wav_in,) = (tmp_path / "in").glob("*.wav")
    (wav_out,) = (tmp_path / "out").glob("*.wav")
    assert rms(wav_in, 0) > 1000 and rms(wav_out, 0) > 1000
    kinds = [e["kind"] for e in json.load(open(next((tmp_path / "out").glob("*.json"))))["events"]]
    assert kinds[:3] == ["dialing", "sip", "answered"]


def test_sip_allow_drops_strangers():
    from strands_phone.sip import Sip, allowed_networks

    seen = []

    class H:
        def on_sip(self, data, addr):
            seen.append(addr)

    sip = Sip(H(), allowed_networks("3.80.16.0/23"))
    sip.datagram_received(b"OPTIONS sip:x SIP/2.0\r\n\r\n", ("203.0.113.9", 5060))
    sip.datagram_received(b"OPTIONS sip:x SIP/2.0\r\n\r\n", ("3.80.17.24", 5060))
    assert seen == [("3.80.17.24", 5060)]


def test_malformed_sip_does_not_raise():
    from strands_phone.sip import Sip

    class Boom:
        def on_sip(self, data, addr):
            raise KeyError("from")

    Sip(Boom()).datagram_received(b"garbage\r\n\r\n", ("3.80.17.24", 5060))
