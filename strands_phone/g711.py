"""G.711 u-law <-> 16-bit PCM without audioop (removed in Python 3.13)."""

from __future__ import annotations

from array import array

_BIAS, _CLIP = 0x84, 8159  # CPython audioop's 14-bit G.711 (st_14linear2ulaw)
_SEG_END = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)


def _encode(sample: int) -> int:
    v = sample >> 2
    mask = 0x7F if v < 0 else 0xFF
    v = min(-v if v < 0 else v, _CLIP) + (_BIAS >> 2)
    seg = next((i for i, end in enumerate(_SEG_END) if v <= end), 8)
    if seg >= 8:
        return 0x7F ^ mask
    return ((seg << 4) | ((v >> (seg + 1)) & 0x0F)) ^ mask


def _decode(byte: int) -> int:
    byte = ~byte & 0xFF
    sign, exponent, mantissa = byte & 0x80, (byte >> 4) & 0x07, byte & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if sign else sample


_ENC = bytes(_encode(v - 65536 if v > 32767 else v) for v in range(65536))  # index = sample & 0xFFFF
_DEC = array("h", (_decode(b) for b in range(256)))


def lin2ulaw(pcm: bytes) -> bytes:
    """Little-endian PCM16 -> u-law, one byte per sample."""
    samples = array("h", pcm)
    return bytes(_ENC[s & 0xFFFF] for s in samples)


def ulaw2lin(data: bytes) -> bytes:
    """u-law -> little-endian PCM16."""
    return array("h", (_DEC[b] for b in data)).tobytes()
