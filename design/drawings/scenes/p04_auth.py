"""P04: how each model is authorised on the host."""

from scene import Scene


def scene() -> Scene:
    s = Scene(
        "p04_auth",
        "Credentials that never expire",
        "Nova Sonic signs with the EC2 instance role; gpt-realtime-2 reads OPENAI_API_KEY from a root-only file. Nothing secret lives in the repo.",
        "Left, MODEL_PROVIDER nova: the EC2 instance role strands-phone-ec2 (green) signs with SigV4, the stream "
        "is authorised against bedrock:InvokeModel and opens. Right, MODEL_PROVIDER openai: "
        "OPENAI_API_KEY from /etc/strands-phone.env, mode 600, goes as a bearer token over a websocket to gpt-realtime-2.",
        h=420,
    )
    s.section(40, 122, "MODEL_PROVIDER=nova")
    s.box(
        40,
        134,
        250,
        92,
        "instance role",
        "strands-phone-ec2, rotated by AWS",
        accent=True,
        size=14,
        subsize=12,
        id="role",
    )
    s.box(340, 134, 250, 92, "Nova 2 Sonic", "InvokeModelWithBidirectionalStream", size=14, subsize=12, id="nova")
    s.arrow([(290, 180), (340, 180)], accent=True, label="SigV4", label_dx=-18, label_dy=-8, id="sig")
    s.para(
        40,
        252,
        "The stream is authorised against bedrock:InvokeModel: a role with only the stream action is denied.",
        550,
    )

    s.section(660, 122, "MODEL_PROVIDER=openai")
    s.box(
        660,
        134,
        250,
        92,
        "/etc/strands-phone.env",
        "root, mode 600, written by deploy.sh",
        size=14,
        subsize=12,
        id="env",
    )
    s.box(950, 134, 210, 92, "gpt-realtime-2", "wss, 24 kHz PCM", size=14, subsize=12, id="oai")
    s.arrow([(910, 180), (950, 180)], label="Bearer", label_dx=-20, label_dy=-8, id="bear")
    s.para(
        660,
        252,
        "OPENAI_API_KEY comes from .secrets.env on your machine, which git ignores, and never reaches the repo.",
        500,
    )
    s.chips(660, 300, ["infra/up.sh", "deploy/deploy.sh", ".secrets.env", "MODEL_PROVIDER"])
    s.motion = [("sig", "flow"), ("bear", "flow"), ("role", "pulse")]
    s.footnote(372, "Switch models by changing one line in .secrets.env and running deploy/deploy.sh again.")
    return s
