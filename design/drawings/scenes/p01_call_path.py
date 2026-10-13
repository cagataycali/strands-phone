"""P01: the call path. Phone network to a Strands BidiAgent and back, both directions at once."""

from scene import Scene


def scene() -> Scene:
    s = Scene(
        "p01_call_path",
        "A phone call into a Strands agent",
        "Any phone dials a Chime SDK number; SIP and RTP reach strands-phone on EC2, which streams the call into a BidiAgent and plays its voice back.",
        "Five cards left to right: a phone on the phone network, the Chime SDK Voice Connector holding the number, "
        "strands-phone on EC2 (the one green card) speaking SIP and RTP, the Strands BidiAgent with its tools, and "
        "the speech model, Nova 2 Sonic or gpt-realtime-2. Wires between each pair carry the caller's audio right "
        "and the agent's audio left at the same time. Below, the two audio paths and the measured timings.",
        h=600,
    )
    xs, w, y, h = [40, 275, 510, 745, 980], 180, 150, 118
    cards = [
        ("phone", "any phone on the phone network", False, "c_phone"),
        ("Voice Connector", "Chime SDK: the number and a SIP trunk", False, "c_vc"),
        ("strands-phone", "EC2: SIP, RTP, a 20 ms audio clock", True, "c_host"),
        ("BidiAgent", "strands.bidi with tools and barge-in", False, "c_agent"),
        ("speech model", "Nova 2 Sonic or gpt-realtime-2", False, "c_model"),
    ]
    s.section(40, 128, "the path")
    for x, (t, sub, acc, cid) in zip(xs, cards):
        s.box(x, y, w, h, t, sub, accent=acc, size=14, subsize=12, id=cid)
    labels = ["PSTN", "SIP/RTP", "PCM16", "audio"]
    for i in range(4):
        a, b = xs[i] + w, xs[i + 1]
        s.arrow([(a, y + 44), (b, y + 44)], label=labels[i], label_dx=0, label_dy=-8, label_anchor="middle", id=f"r{i}")
        s.arrow([(b, y + 84), (a, y + 84)], id=f"l{i}")
    s.motion = (
        [(c[3], "visit") for c in cards] + [(f"r{i}", "flow") for i in range(4)] + [(f"l{i}", "flow") for i in range(4)]
    )

    s.section(40, 322, "caller to agent")
    s.chips(40, 334, ["RTP PCMU", "G.711 decode", "PCM16 8 kHz", "agent.send(AudioDelta)"])
    s.section(620, 322, "agent to caller")
    s.chips(620, 334, ["agent.receive()", "playout buffer", "20 ms clock", "RTP PCMU"])
    s.para(
        40,
        390,
        "Both run at once. When the caller talks over the agent, the model sends bidi_barge_in and the "
        "unplayed buffer is dropped.",
        520,
        size=12.5,
    )
    s.para(
        620,
        390,
        "Nova 2 Sonic speaks 8 kHz, the line's own rate. gpt-realtime-2 speaks 24 kHz, so the bridge "
        "resamples both ways.",
        540,
        size=12.5,
    )

    s.section(40, 462, "measured on a real call", accent=True)
    s.chips(
        40,
        474,
        ["answered 31 ms", "first audio 0.82 s", "replies 0.13 to 0.68 s", "tool call", "agent hung up"],
        accent="first audio 0.82 s",
    )
    s.footnote(548, "One process per call: systemd restarts strands-phone to listen again the moment a call ends.")
    return s
