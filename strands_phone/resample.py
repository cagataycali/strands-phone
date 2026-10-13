"""8 kHz <-> 24 kHz for models that only speak 24 kHz PCM (OpenAI Realtime), streaming and stateful.

Windowed-sinc FIR low-pass at the phone band's 4 kHz Nyquist, 3x zero-stuff up, 3x decimate down.
"""

from __future__ import annotations

import math
from array import array

_TAPS = 31


def _lowpass(cutoff: float, rate: int, taps: int = _TAPS) -> list[float]:
    m = taps - 1
    h = []
    for n in range(taps):
        x = n - m / 2
        sinc = 2 * cutoff / rate if x == 0 else math.sin(2 * math.pi * cutoff / rate * x) / (math.pi * x)
        h.append(sinc * (0.54 - 0.46 * math.cos(2 * math.pi * n / m)))  # Hamming
    s = sum(h)
    return [v / s for v in h]


_H = _lowpass(3600, 24000)


def _clip(v: float) -> int:
    return -32768 if v < -32768 else 32767 if v > 32767 else int(v)


class Up3:
    """8 kHz PCM16 -> 24 kHz PCM16."""

    def __init__(self) -> None:
        self._hist = [0.0] * (_TAPS - 1)

    def __call__(self, pcm: bytes) -> bytes:
        x = self._hist + [v for s in array("h", pcm) for v in (3.0 * s, 0.0, 0.0)]
        out = array("h", (_clip(sum(h * x[i + k] for k, h in enumerate(_H))) for i in range(len(x) - _TAPS + 1)))
        self._hist = x[-(_TAPS - 1) :]
        return out.tobytes()


class Down3:
    """24 kHz PCM16 -> 8 kHz PCM16 (chunks of any length; the phase carries over)."""

    def __init__(self) -> None:
        self._hist = [0.0] * (_TAPS - 1)
        self._phase = 0

    def __call__(self, pcm: bytes) -> bytes:
        x = self._hist + [float(s) for s in array("h", pcm)]
        n = len(x) - _TAPS + 1
        out = array("h", (_clip(sum(h * x[i + k] for k, h in enumerate(_H))) for i in range(self._phase, n, 3)))
        self._phase = (self._phase - n) % 3
        self._hist = x[-(_TAPS - 1) :]
        return out.tobytes()
