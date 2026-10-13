"""P03: the audio bridge inside strands-phone."""

from scene import Scene


def scene() -> Scene:
    s = Scene(
        "p03_audio_bridge",
        "The audio bridge",
        "Caller audio goes straight into the agent; agent audio waits in a buffer that a 20 ms clock drains onto the line. Barge-in empties the buffer.",
        "Top lane, left to right: RTP packet in, G.711 decode to PCM16 at 8 kHz, Up3 to 24 kHz only for gpt-realtime-2, "
        "agent.send(AudioDelta). Bottom lane, right to left: agent.receive() audio events, Down3 to 8 kHz only for "
        "gpt-realtime-2, the playout buffer, the 20 ms clock (the green card) which sends agent audio or a -60 dBFS "
        "noise floor, RTP out. A barge-in event wire clears the playout buffer.",
        h=560,
    )
    xs, w = [40, 330, 620, 910], 250
    s.section(40, 122, "caller to agent, as it arrives")
    top = [
        ("RTP in", "PCMU payload, any packet size"),
        ("G.711 decode", "u-law to PCM16, 8 kHz"),
        (
            "Up3",
            "8 to 24 kHz, only for gpt-realtime-2",
        ),
        ("agent.send()", "one AudioDelta per packet"),
    ]
    for i, (x, (t, sub)) in enumerate(zip(xs, top)):
        s.box(x, 134, w, 84, t, sub, dashed=(t == "Up3"), size=14, subsize=12, id=f"t{i}")
        if i:
            s.arrow([(xs[i - 1] + w, 176), (x, 176)], id=f"ta{i}")
    s.section(40, 274, "agent to caller, paced")
    bot = [
        ("RTP out", "PCMU, 160 samples per packet"),
        ("20 ms clock", "agent audio, or a -60 dBFS noise floor"),
        ("playout buffer", "PCM16 8 kHz waiting to play"),
        ("agent.receive()", "bidi_audio_delta events"),
    ]
    for i, (x, (t, sub)) in enumerate(zip(xs, bot)):
        s.box(x, 286, w, 84, t, sub, accent=(t == "20 ms clock"), size=14, subsize=12, id=f"b{i}")
        if i:
            s.arrow([(x, 328), (xs[i - 1] + w, 328)], id=f"ba{i}")
    s.chip(910, 384, "Down3 for 24 kHz output")
    s.chip(910, 456, "bidi_barge_in", accent=False)
    s.arrow(
        [(910, 468), (745, 468), (745, 370)],
        dashed=True,
        label="clears the buffer",
        label_dx=0,
        label_dy=-8,
        label_anchor="middle",
        id="barge",
    )
    s.motion = [
        ("ta1", "flow"),
        ("ta2", "flow"),
        ("ta3", "flow"),
        ("ba1", "flow"),
        ("ba2", "flow"),
        ("ba3", "flow"),
        ("b1", "pulse"),
        ("barge", "flow"),
    ]
    s.footnote(520, "The line is never digitally silent: the model only answers while audio frames are flowing.")
    return s
