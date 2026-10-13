"""P05: the design. What runs where: the number and trunk, the host, the agent, the two models."""

from scene import Scene


def scene() -> Scene:
    s = Scene(
        "p05_design",
        "What runs where",
        "Chime SDK owns the number and the trunk, one EC2 host runs strands-phone, and the BidiAgent talks to the model.",
        "Left, the phone network wired both ways to the Voice Connector, which holds the number and a SIP trunk: "
        "origination sends incoming calls to the host, termination accepts outgoing calls only from the host's "
        "Elastic IP. Middle, a dashed EC2 box: strands-phone.service under systemd, InboundCall that answers and Call "
        "that dials, and the BidiAgent (green) with its tools. Right, the two models: Nova 2 Sonic signed by the "
        "instance role, and gpt-realtime-2 with OPENAI_API_KEY. Below, the two commands that build and ship it.",
        h=640,
    )
    s.section(40, 122, "phone side")
    s.box(40, 150, 150, 96, "phone", "any phone, any network", size=14, subsize=12, id="d_phone")
    s.box(
        240,
        150,
        250,
        190,
        "Voice Connector",
        "Chime SDK: the number and a SIP trunk. Origination sends calls in to "
        "the host; termination takes calls out only from the host's Elastic IP.",
        size=14,
        subsize=12,
        id="d_vc",
    )
    s.arrow([(190, 198), (240, 198)], head="both", id="w_pstn")

    s.section(540, 122, "one host")
    s.box(540, 134, 380, 356, "EC2 + Elastic IP", None, dashed=True, size=14)
    s.box(
        560,
        176,
        340,
        76,
        "strands-phone.service",
        "systemd: one call per process, then listen again",
        size=13,
        subsize=12,
        id="d_svc",
    )
    s.box(560, 268, 160, 84, "InboundCall", "answers: 100, 180, 200", size=13, subsize=12, id="d_in")
    s.box(740, 268, 160, 84, "Call", "dials: INVITE, ACK, BYE", size=13, subsize=12, id="d_out")
    s.box(
        560,
        372,
        340,
        98,
        "BidiAgent",
        "strands.bidi, current_time and hang_up, barge-in, a stereo WAV per call",
        accent=True,
        size=13,
        subsize=12,
        id="d_agent",
    )
    s.arrow([(490, 214), (540, 214)], label="SIP in", label_dx=0, label_dy=-8, label_anchor="middle", id="w_orig")
    s.arrow([(540, 300), (490, 300)], label="SIP out", label_dx=0, label_dy=-8, label_anchor="middle", id="w_term")

    s.section(970, 122, "the model")
    s.box(970, 300, 190, 84, "Nova 2 Sonic", "8 kHz, instance role", size=13, subsize=12, id="d_nova")
    s.box(970, 406, 190, 84, "gpt-realtime-2", "24 kHz, OPENAI_API_KEY", size=13, subsize=12, id="d_oai")
    s.arrow([(900, 404), (935, 404), (935, 342), (970, 342)], head="both", id="w_nova")
    s.arrow([(900, 440), (935, 440), (935, 448), (970, 448)], head="both", dashed=True, id="w_oai")
    s.chips(970, 150, ["MODEL_PROVIDER"])
    s.para(970, 196, "nova or openai: one line in .secrets.env, then deploy again.", 190, size=12)

    s.section(40, 532, "two commands", accent=True)
    s.chips(40, 544, ["infra/up.sh", "deploy/deploy.sh"], accent="deploy/deploy.sh")
    s.para(
        330,
        552,
        "up.sh creates the number, the Voice Connector, the host, its security group and its role. "
        "deploy.sh ships this repo and restarts the service.",
        820,
        size=12.5,
    )
    s.motion = [
        ("w_pstn", "flow"),
        ("w_orig", "flow"),
        ("w_term", "flow"),
        ("w_nova", "flow"),
        ("w_oai", "flow"),
        ("d_svc", "visit"),
        ("d_in", "visit"),
        ("d_agent", "visit"),
        ("d_nova", "visit"),
    ]
    s.footnote(
        608,
        "No long-lived AWS secrets on the host: the role rotates itself, and an OpenAI key stays in a root-only file.",
    )
    return s
