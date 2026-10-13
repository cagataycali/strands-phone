"""P02: one inbound call, message by message."""

from scene import Scene


def scene() -> Scene:
    s = Scene(
        "p02_one_call",
        "One call, message by message",
        "The Voice Connector sends an INVITE; strands-phone opens the model while the line rings, answers, and the audio flows until someone sends BYE.",
        "Three lifelines: the Voice Connector, strands-phone and the BidiAgent. Messages top to bottom: INVITE with "
        "the caller's SDP, 100 Trying, 180 Ringing while agent.start() opens the model, 200 OK with our SDP, ACK, then "
        "RTP both ways (the green wire) while the agent is cued to greet; finally BYE and 200 OK. Outbound calls are "
        "the same ladder with the roles swapped.",
        h=720,
    )
    A, B, C = 200, 600, 1000
    for x, t, sub in [
        (A, "Voice Connector", "Chime SDK"),
        (B, "strands-phone", "InboundCall"),
        (C, "BidiAgent", "and the model"),
    ]:
        s.box(x - 110, 120, 220, 64, t, sub, accent=(x == B), size=14, subsize=12)
        s.arrow([(x, 184), (x, 650)], dashed=True, head=False)
    rows = [
        (A, B, "INVITE + caller SDP", "m1"),
        (B, A, "100 Trying", "m2"),
        (B, A, "180 Ringing", "m3"),
        (B, C, "agent.start()", "m4"),
        (B, A, "200 OK + our SDP", "m5"),
        (A, B, "ACK", "m6"),
        (B, C, "greet: one short sentence", "m7"),
    ]
    y = 214
    for a, b, label, mid in rows:
        s.arrow([(a, y), (b, y)], label=label, label_dx=-60 if a < b else -60, label_dy=-7, id=mid)
        y += 46
    s.arrow(
        [(A, y + 6), (B, y + 6)],
        accent=True,
        head="both",
        label="RTP PCMU, 20 ms frames",
        label_dx=-80,
        label_dy=-8,
        id="rtp",
    )
    s.arrow(
        [(B, y + 6), (C, y + 6)],
        accent=True,
        head="both",
        label="AudioDelta / audio events",
        label_dx=-86,
        label_dy=-8,
        id="pcm",
    )
    y += 52
    s.arrow([(A, y), (B, y)], label="BYE", label_dx=-14, label_dy=-7, id="m8")
    s.arrow([(B, y + 36), (A, y + 36)], label="200 OK", label_dx=-22, label_dy=-7, id="m9")
    s.motion = [(m, "flow") for m in ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "rtp", "pcm", "m8", "m9"]]
    s.footnote(
        688,
        "Outbound is the same ladder mirrored: strands-phone sends the INVITE, the Voice Connector answers for the callee.",
    )
    return s
