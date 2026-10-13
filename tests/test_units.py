import math
import struct
import sys

import pytest

from strands_phone.g711 import lin2ulaw, ulaw2lin
from strands_phone.sip import parse_sip, sdp_target


@pytest.mark.skipif(sys.version_info >= (3, 13), reason="audioop is gone in 3.13")
def test_g711_matches_audioop_bit_for_bit():
    import audioop  # noqa: F401  (deprecated, gone in 3.13)

    pcm = struct.pack("<65536h", *range(-32768, 32768))
    assert lin2ulaw(pcm) == audioop.lin2ulaw(pcm, 2)
    every = bytes(range(256))
    assert ulaw2lin(every) == audioop.ulaw2lin(every, 2)


def test_g711_round_trip_keeps_a_tone():
    tone = struct.pack("<160h", *(int(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(160)))
    back = struct.unpack("<160h", ulaw2lin(lin2ulaw(tone)))
    assert max(abs(a - b) for a, b in zip(struct.unpack("<160h", tone), back)) < 300


def test_parse_sip_and_sdp():
    msg = (
        b"SIP/2.0 200 OK\r\nVia: SIP/2.0/UDP 1.2.3.4:5060;branch=z9hG4bKx\r\nTo: <sip:+1555@vc>;tag=abc\r\n"
        b"Contact: <sip:+1555@3.80.16.1:5060>;expires=60\r\nContent-Length: 50\r\n\r\n"
        b"v=0\r\nc=IN IP4 3.80.17.24\r\nm=audio 55276 RTP/AVP 0 101\r\n"
    )
    start, h, body = parse_sip(msg)
    assert start == "SIP/2.0 200 OK"
    assert h["to"] == ["<sip:+1555@vc>;tag=abc"]
    assert sdp_target(body) == ("3.80.17.24", 55276)


def test_resample_keeps_a_phone_band_tone_and_kills_aliases():
    from strands_phone.resample import Down3, Up3

    def tone(f, rate, n):
        return struct.pack(f"<{n}h", *(int(8000 * math.sin(2 * math.pi * f * i / rate)) for i in range(n)))

    def rms(b):
        s = struct.unpack(f"<{len(b) // 2}h", b)[200:]
        return math.sqrt(sum(v * v for v in s) / len(s))

    up, down = Up3(), Down3()
    hi = b"".join(up(tone(1000, 8000, 160)[i : i + 320]) for i in range(0, 320, 320))
    assert len(up(tone(1000, 8000, 160))) == 960  # 20 ms in -> 20 ms out at 24 kHz
    voice = b"".join(down(tone(1000, 24000, 2400)[i : i + 700]) for i in range(0, 4800, 700))  # odd chunks
    assert len(voice) == 1600 and 4500 < rms(voice) < 6500  # 1 kHz passes (8000/sqrt2 ≈ 5657)
    alias = Down3()(tone(9000, 24000, 2400))  # 9 kHz would fold to 1 kHz without the filter
    assert rms(alias) < 400
    assert hi
