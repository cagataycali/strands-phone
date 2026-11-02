"""PHONE_PERSONA=leaf: the confirmation gate, the robot tools against a fake LEAF dashboard, the spoken stop, and a
scripted SIP call whose callee runs the real LEAF tools. LEAF_E2E_URL + LEAF_E2E_TOKEN run it against a real one."""

import asyncio
import base64
import json
import logging
import math
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from strands_phone import Call, InboundCall
from strands_phone import leaf as L

CODE = "test-code-" + "7" * 6
TOKEN = "phone-token-" + "t" * 30


class FakeLeaf:
    """A LEAF dashboard that records every request and enforces the phone token like server.PHONE_SCOPE."""

    def __init__(self):
        self.calls = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _route(self, method):
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else None
                fake.calls.append((method, self.path, body, self.headers.get("authorization")))
                if self.headers.get("authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"status": "error", "message": "authentication required"})
                if self.path in ("/api/robot/damp", "/api/robot/clear_fault"):
                    return self._send(403, {"status": "error", "scope": "phone"})
                r = {
                    ("GET", "/api/robot/state"): {"status": "success", "state": "ACTIVE", "mode": "walk"},
                    ("GET", "/api/robot/telemetry"): {"battery": {"soc_pct": 64.0, "charging": False}},
                    ("GET", "/api/robot/modes"): {
                        "available": [{"mode": "walk", "name": "Walk"}, {"mode": "party_dance", "name": "Party dance"}]
                    },
                    ("GET", "/api/behaviors"): [
                        {"id": "hri:play-wave", "name": "Wave", "kind": "behavior"},
                        {"id": "hri:give", "name": "Give", "kind": "behavior"},
                    ],
                    ("GET", "/api/cameras"): [{"id": "left", "kind": "rgb", "available": True}],
                    ("POST", "/api/robot/mode"): {"ok": True, "status": "success"},
                    ("POST", "/api/behaviors/run"): {"ok": True, "status": "success"},
                    ("POST", "/api/behaviors/cancel"): {"ok": True},
                    ("POST", "/api/robot/walk"): {"status": "success", "walked_m": 0.75, "steps_walked": 3.0},
                    ("POST", "/api/robot/turn"): {"status": "success", "turned_deg": 90.0},
                    ("POST", "/api/robot/stop"): {"status": "success", "damped": False, "message": "Stopped moving."},
                }.get((method, self.path))
                if self.path == "/api/camera/left/snapshot":
                    return self._send(200, b"\xff\xd8fakejpeg\xff\xd9", "image/jpeg")
                if r is None:
                    return self._send(403, {"status": "error", "scope": "phone"})
                return self._send(200, r)

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def paths(self):
        return [(m, p) for m, p, *_ in self.calls]

    def close(self):
        self.srv.shutdown()


class FakeCall:
    def __init__(self, loop=None):
        self.events, self.agent, self.loop = [], None, loop
        self.hangup_after_audio, self.last_agent_audio = False, 0.0

    def mark(self, kind, **kw):
        self.events.append({"kind": kind, **kw})


class ImageSink:
    def __init__(self):
        self.sent = []

    async def send(self, item):
        self.sent.append(item)


@pytest.fixture
def leaf():
    f = FakeLeaf()
    yield f
    f.close()


def tools_by_name(call, gate, client, images=True):
    return {t.tool_name: t for t in L.build_tools(call, gate, client, images=images)}


def test_every_robot_tool_is_gated_and_sends_nothing(leaf):
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert set(t) == {
        "confirm",
        "stop_moving",
        "hang_up",
        "robot_state",
        "look",
        "change_mode",
        "list_behaviors",
        "run_behavior",
        "cancel_behavior",
        "walk",
        "turn",
    }
    for name, args in (
        ("robot_state", {}),
        ("look", {}),
        ("change_mode", {"mode": "sit"}),
        ("list_behaviors", {}),
        ("run_behavior", {"behavior": "wave"}),
        ("cancel_behavior", {}),
        ("walk", {"steps": 3}),
        ("turn", {"degrees": 90}),
    ):
        assert t[name](**args) == L.GATE_MSG, name
    assert leaf.calls == []


def test_no_damp_anywhere():
    import inspect

    src = inspect.getsource(L)
    assert "/api/robot/damp" not in src and "clear_fault" not in src and "/api/robot/active" not in src
    names = {t.tool_name for t in L.build_tools(FakeCall(), L.ConfirmGate(CODE), L.LeafClient("http://x", TOKEN))}
    assert not any("damp" in n or "fault" in n or "state_set" in n for n in names)


def test_unconfirmed_stranger_cannot_even_stop_but_can_hang_up(leaf):
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert t["stop_moving"]() == L.GATE_MSG and leaf.calls == []  # owner decision 01:35Z: stranger = nothing
    assert "Hanging up" in t["hang_up"]() and call.hangup_after_audio
    for _ in range(3):  # still nothing after the gate locked
        t["confirm"](code="nope")
    assert gate.locked and t["stop_moving"]() == L.GATE_MSG and leaf.calls == []


def test_confirmed_stranger_can_stop(leaf):
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert t["confirm"](code=CODE)["status"] == "success" and gate.can_stop
    out = t["stop_moving"]()
    assert out["damped"] is False and out["status"] == "success"
    assert leaf.paths() == [("POST", "/api/robot/stop")] and leaf.calls[0][3] == f"Bearer {TOKEN}"


def test_three_wrong_keys_lock_confirm_for_the_call(leaf, caplog):
    caplog.set_level(logging.INFO, logger="strands_phone.leaf")
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert t["confirm"](code="wrong1")["tries_left"] == 2
    assert t["confirm"](code="wrong2")["tries_left"] == 1
    assert t["confirm"](code="wrong3")["locked"] is True
    r = t["confirm"](code=CODE)  # the right key no longer helps in this call
    assert r["status"] == "error" and r["locked"] and not gate.unlocked
    assert t["walk"](steps=2) == L.GATE_MSG and leaf.calls == []
    assert CODE not in caplog.text and "wrong1" not in caplog.text  # no key in the logs
    assert [e["kind"] for e in call.events] == ["confirm"] * 4
    assert all(CODE not in json.dumps(e) for e in call.events)


def test_spoken_key_normalisation_and_a_new_call_starts_locked(leaf):
    gate = L.ConfirmGate("banana4321")
    assert gate.check("Banana 4-3-2-1.")["status"] == "success" and gate.unlocked
    assert not L.ConfirmGate("banana4321").unlocked  # unlock lasts for one call (one gate per call)
    assert L.ConfirmGate("banana4321").check("banana 4322")["status"] == "error"


def test_no_code_configured_means_locked_forever(monkeypatch):
    monkeypatch.delenv("LEAF_PHONE_CONFIRM_CODE", raising=False)
    gate = L.ConfirmGate()
    assert not gate.configured
    assert gate.check("")["status"] == "error" and gate.check("anything")["status"] == "error" and not gate.unlocked


def test_code_comes_from_env(monkeypatch):
    monkeypatch.setenv("LEAF_PHONE_CONFIRM_CODE", CODE)
    assert L.ConfirmGate().check(CODE)["status"] == "success"


def test_unlocked_tools_drive_the_dashboard_with_the_phone_token(leaf):
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    call, gate = FakeCall(loop), L.ConfirmGate(CODE)
    call.agent = ImageSink()
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert t["confirm"](code=CODE)["status"] == "success"
    st = t["robot_state"]()
    assert st["state"] == "ACTIVE" and st["mode"] == "walk" and st["battery_pct"] == 64
    assert t["look"](question="who is there?")["status"] == "success"
    time.sleep(0.2)
    assert call.agent.sent and call.agent.sent[0]["image"]["format"] == "jpeg"
    assert t["change_mode"](mode="party dance")["ok"]
    assert t["run_behavior"](behavior="wave")["ok"]
    assert t["walk"](steps=3)["walked_m"] == 0.75
    assert t["turn"](degrees=-90)["turned_deg"] == 90.0
    assert t["list_behaviors"]()["behaviors"] == ["Wave", "Give"]
    assert t["cancel_behavior"]()["ok"]
    bodies = {p: b for m, p, b, _ in leaf.calls if m == "POST"}
    assert bodies["/api/robot/mode"] == {"mode": "party_dance"}
    assert bodies["/api/behaviors/run"] == {"id": "hri:play-wave"}
    assert bodies["/api/robot/walk"] == {"direction": "forward", "steps": 3}
    assert bodies["/api/robot/turn"] == {"degrees": -90}
    assert all(a == f"Bearer {TOKEN}" for *_, a in leaf.calls)
    loop.call_soon_threadsafe(loop.stop)


def test_look_without_an_image_model_says_so(leaf):
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN), images=False)
    t["confirm"](code=CODE)
    assert "cannot see" in t["look"]()["message"]


def test_dashboard_down_is_an_honest_error():
    call, gate = FakeCall(), L.ConfirmGate(CODE)
    t = tools_by_name(call, gate, L.LeafClient("http://127.0.0.1:9", TOKEN, timeout=0.5))
    t["confirm"](code=CODE)
    r = t["walk"](steps=2)
    assert r["status"] == "error" and r["unreachable"]
    assert t["stop_moving"]()["status"] == "error"


@pytest.mark.parametrize("text", ["stop", "Stop!", "LEAF stop", "stop now", "halt", "freeze", "emergency stop", "damp"])
def test_stop_phrases(text):
    assert L.is_stop_phrase(text)


@pytest.mark.parametrize("text", ["don't stop dancing", "stop at the kitchen and wait for me there", "", "walk"])
def test_not_stop_phrases(text):
    assert not L.is_stop_phrase(text)


def test_persona_switch(monkeypatch):
    from strands_phone import agent as A

    monkeypatch.delenv("PHONE_PERSONA", raising=False)
    assert A.persona() == "default"
    monkeypatch.setenv("PHONE_PERSONA", "leaf")
    assert A.persona() == "leaf"
    monkeypatch.setenv("PHONE_PERSONA", "robot")
    with pytest.raises(ValueError):
        A.persona()


def test_leaf_prompt_is_first_person_robot_and_names_the_gate():
    p = L.leaf_prompt(inbound=True)
    assert "You are LEAF" in p and "first person" in p and "confirm(code)" in p and "hang_up" in p
    assert "never say a key out loud" in " ".join(p.lower().split()) and "AI" in p  # "Never say you are an AI"
    assert CODE not in p and "banana4321" not in p


# ---------------------------------------------------------------- scripted call over real SIP + RTP
class ScriptedLeafAgent:
    """Stands in for the realtime model on a real loopback SIP call: plays a fixed conversation by calling the REAL
    LEAF phone tools (built by agent.make_leaf_agent's pieces) and emitting the caller's transcripts."""

    SCRIPT = [
        ("user", "can you wave at me?"),
        ("tool", "run_behavior", {"behavior": "wave"}),  # gated
        ("user", "the key is banana"),
        ("tool", "confirm", {"code": "banana"}),  # wrong 1/3
        ("user", "sorry, it's " + CODE),
        ("tool", "confirm", {"code": CODE}),
        ("tool", "run_behavior", {"behavior": "wave"}),
        ("tool", "walk", {"steps": 3}),
        ("user", "stop!"),  # caught by the transcript hook before the model
        ("tool", "stop_moving", {}),
        ("tool", "hang_up", {}),
    ]

    def __init__(self, call, url, token, code):
        self.call, self.results, self.sent = call, [], []
        self.gate = L.ConfirmGate.for_caller(call.caller_number, code, OWNERS)
        self.client = L.LeafClient(url, token)
        self.tools = {t.tool_name: t for t in L.build_tools(call, self.gate, self.client)}
        L.install_stop_hook(call, self.client, self.gate)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def send(self, item):
        self.sent.append(item)

    async def receive(self):
        tone = struct.pack("<1600h", *(int(6000 * math.sin(2 * math.pi * 300 * i / 8000)) for i in range(1600)))
        yield {"type": "bidi_audio_delta", "audio": base64.b64encode(tone).decode(), "sample_rate": 8000}
        for step in self.SCRIPT:
            if step[0] == "user":
                yield {"type": "bidi_transcript_block", "role": "user", "transcript": step[1]}
            else:
                _, name, args = step
                yield {"type": "bidi_tool_use_blocks", "tool_uses": [{"name": name}]}
                out = await asyncio.to_thread(self.tools[name], **args)
                self.results.append((name, out))
                yield {"type": "bidi_audio_delta", "audio": base64.b64encode(tone).decode(), "sample_rate": 8000}
            await asyncio.sleep(0.05)
        await asyncio.Event().wait()


class Caller:
    """The person dialing: silent, hangs up when the callee does."""

    def __init__(self, call):
        self.call = call

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def send(self, item):
        pass

    async def receive(self):
        await asyncio.Event().wait()
        yield {}


def _scripted_call(tmp_path, url, token, code, ports, from_number="+15550009999", cls=None):
    agents = {}

    def callee_factory(call, inbound=False):
        agents["leaf"] = (cls or ScriptedLeafAgent)(call, url, token, code)
        return agents["leaf"]

    async def go():
        common = dict(public_ip="127.0.0.1", caller_id="+18623823007", record=True)
        callee = InboundCall(
            agent_factory=callee_factory, sip_port=ports[0], rtp_port=ports[1], calls_dir=str(tmp_path / "in"), **common
        )
        caller = Call(
            "+18623823007",
            agent_factory=lambda c, inbound=False: Caller(c),
            vc_host="127.0.0.1",
            vc_port=ports[0],
            sip_port=ports[2],
            rtp_port=ports[3],
            calls_dir=str(tmp_path / "out"),
            **{**common, "caller_id": from_number},  # the From number the callee sees
        )
        await asyncio.wait_for(asyncio.gather(callee.run(), caller.run()), 40)
        return callee, caller

    callee, caller = asyncio.run(go())
    return callee, caller, agents["leaf"]


def _check_script(callee, caller, a):
    res = dict()
    for name, out in a.results:
        res.setdefault(name, []).append(out)
    assert res["run_behavior"][0] == L.GATE_MSG  # before the key: nothing ran
    assert res["confirm"][0]["tries_left"] == 2 and res["confirm"][1]["status"] == "success"
    assert res["run_behavior"][1].get("status") != L.GATE_MSG
    assert res["stop_moving"][0]["damped"] is False
    kinds = [e["kind"] for e in callee.events]
    assert "stop" in kinds and [e for e in callee.events if e["kind"] == "stop"][0]["via"] == "transcript"
    assert callee.end_reason == "agent hung up" and caller.end_reason == "callee hung up"
    assert all(code_not_in(e) for e in callee.events)
    return res


def code_not_in(e):
    return CODE not in json.dumps({k: v for k, v in e.items() if k != "text"})  # transcripts hold what the caller said


def test_scripted_call_against_fake_leaf(tmp_path, leaf):
    callee, caller, a = _scripted_call(tmp_path, leaf.url, TOKEN, CODE, (16060, 16070, 16062, 16072))
    _check_script(callee, caller, a)
    posts = [p for m, p in leaf.paths() if m == "POST"]
    # gated run_behavior sent nothing; after the key: behaviour + walk; stop twice (spoken hook + tool)
    assert posts.count("/api/behaviors/run") == 1 and posts.count("/api/robot/walk") == 1
    assert posts.count("/api/robot/stop") == 2
    assert "/api/robot/damp" not in posts


@pytest.mark.skipif(
    not os.environ.get("LEAF_E2E_URL"), reason="set LEAF_E2E_URL + LEAF_E2E_TOKEN (+ LEAF_PHONE_CONFIRM_CODE)"
)
def test_scripted_call_against_a_real_leaf_dashboard(tmp_path):
    """E2E: the same call against a running LEAF dashboard (Mac testbed via a Cloudflare quick tunnel). Off-robot the
    robot tools answer honestly (off_robot / not moved); the point is auth, scope, gate and stop end to end."""
    url, token = os.environ["LEAF_E2E_URL"], os.environ["LEAF_E2E_TOKEN"]
    if pin := os.environ.get("LEAF_E2E_RESOLVE"):  # "host:ip" for networks whose DNS blocks trycloudflare.com
        import socket

        host, ip = pin.rsplit(":", 1)
        real = socket.getaddrinfo
        pytest.MonkeyPatch().setattr(socket, "getaddrinfo", lambda h, *a, **k: real(ip if h == host else h, *a, **k))
    code = os.environ.get("LEAF_PHONE_CONFIRM_CODE") or CODE
    script = [
        (s[0], s[1], {"code": code}) if s[0] == "tool" and s[1] == "confirm" and s[2]["code"] == CODE else s
        for s in ScriptedLeafAgent.SCRIPT
    ]
    pytest.MonkeyPatch().setattr(ScriptedLeafAgent, "SCRIPT", script)
    callee, caller, a = _scripted_call(tmp_path, url, token, code, (16160, 16170, 16162, 16172))
    res = {}
    for name, out in a.results:
        res.setdefault(name, []).append(out)
    assert res["run_behavior"][0] == L.GATE_MSG
    assert res["confirm"][1]["status"] == "success"
    for out in res["run_behavior"][1:] + res["walk"]:
        assert out.get("http") not in (401, 403), out  # the phone token is in scope on the real dashboard
    assert res["stop_moving"][0].get("damped") is False and res["stop_moving"][0]["status"] == "success"
    print(json.dumps({k: v for k, v in res.items()}, default=str)[:2000])


def test_make_agent_builds_the_leaf_persona(monkeypatch):
    from strands_phone import agent as A

    monkeypatch.setenv("PHONE_PERSONA", "leaf")
    monkeypatch.setenv("MODEL_PROVIDER", "nova")
    monkeypatch.setenv("LEAF_PHONE_CONFIRM_CODE", CODE)
    call = FakeCall()
    ag = A.make_agent(call, inbound=True)
    names = set(ag.tool_names)
    assert {"confirm", "stop_moving", "hang_up", "walk", "look"} <= names and "current_time" not in names
    assert "You are LEAF" in ag.system_prompt and callable(call.on_user_transcript) and not call.leaf_gate.unlocked
    monkeypatch.setenv("PHONE_PERSONA", "default")
    ag = A.make_agent(FakeCall(), inbound=True)
    assert set(ag.tool_names) == {"current_time", "hang_up"}


# ---------------------------------------------------------------- caller-ID policy (owner number trusted)
OWNER = "+15550001234"  # test number; the real one lives only in LEAF_PHONE_OWNER_NUMBERS on the host
OWNERS = frozenset({OWNER})


@pytest.mark.parametrize(
    "raw",
    [
        "+15550001234",
        "+1 (555) 000-1234",
        "1-555-000-1234",
        "15550001234",
        "5550001234",
        "0015550001234",
        "%2B15550001234",
        "tel:+1-555-000-1234",
        "sip:+15550001234@10.0.0.1;user=phone",
        '"Cagatay" <sip:+15550001234@vc.example.com:5060;user=phone>;tag=abc123',
        "<sip:15550001234@1.2.3.4>",
    ],
)
def test_owner_number_format_variants_normalise_to_e164(raw):
    from strands_phone import callerid

    assert callerid.normalize(raw) == OWNER
    assert callerid.is_owner(raw, OWNERS)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "?",
        "anonymous",
        "Anonymous",
        "sip:anonymous@anonymous.invalid",
        "restricted",
        "unavailable",
        "+15550001234x1",  # extension / suffix tricks
        "+155500012345",  # one digit longer
        "+1555000123",  # one digit shorter
        "+15550001234#",
        "+15550001234;+15550009999",
        "sip:+15550009999@h",  # a different number
        "+44 5550001234",  # same digits, other country
        "sip:alice@example.com",
        "555000123",
    ],
)
def test_withheld_spoofed_or_other_numbers_are_strangers(raw):
    from strands_phone import callerid

    assert not callerid.is_owner(raw, OWNERS)
    assert not L.ConfirmGate.for_caller(raw, CODE, OWNERS).owner


def test_owner_numbers_env_is_a_comma_list_in_any_format(monkeypatch):
    from strands_phone import callerid

    monkeypatch.setenv("LEAF_PHONE_OWNER_NUMBERS", " +1 (555) 000-1234 , 5550007777,,junk ")
    assert callerid.owner_numbers() == frozenset({OWNER, "+15550007777"})
    assert callerid.is_owner("sip:+15550007777@h") and not callerid.is_owner(None)
    monkeypatch.delenv("LEAF_PHONE_OWNER_NUMBERS")
    assert callerid.owner_numbers() == frozenset() and not callerid.is_owner(OWNER)  # unset: nobody is trusted


def test_caller_from_invite_headers_and_privacy():
    from strands_phone import callerid

    h = {"from": ['"x" <sip:+15550001234@vc.example>;tag=1']}
    assert callerid.caller_from_invite(h) == OWNER
    assert callerid.caller_from_invite({**h, "privacy": ["id"]}) is None  # caller asked to withhold
    assert callerid.caller_from_invite({"from": ["<sip:anonymous@anonymous.invalid>;tag=2"]}) is None
    assert callerid.caller_from_invite({}) is None
    assert callerid.redact(OWNER) == "+1555***1234" and callerid.redact(None) == "withheld"


def test_owner_call_every_tool_works_without_a_key(leaf, caplog):
    caplog.set_level(logging.INFO, logger="strands_phone.leaf")
    call, gate = FakeCall(), L.ConfirmGate.for_caller(OWNER, CODE, OWNERS)
    assert gate.owner and gate.unlocked and gate.can_stop
    assert OWNER not in caplog.text  # the number is redacted in logs
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    r = t["confirm"](code="anything")
    assert r["status"] == "success" and "not needed" in r["message"] and gate.wrong == 0
    assert t["robot_state"]()["battery_pct"] == 64.0
    assert t["walk"](steps=3)["walked_m"] == 0.75
    assert t["turn"](degrees=90)["turned_deg"] == 90.0
    assert t["run_behavior"](behavior="wave")["status"] == "success"
    assert t["stop_moving"]()["status"] == "success"
    posts = [p for m, p in leaf.paths() if m == "POST"]
    assert posts == ["/api/robot/walk", "/api/robot/turn", "/api/behaviors/run", "/api/robot/stop"]


def test_withheld_caller_is_a_stranger(leaf):
    call, gate = FakeCall(), L.ConfirmGate.for_caller(None, CODE, OWNERS)
    t = tools_by_name(call, gate, L.LeafClient(leaf.url, TOKEN))
    assert t["walk"](steps=1) == L.GATE_MSG and t["stop_moving"]() == L.GATE_MSG and leaf.calls == []


def test_spoken_stop_hook_follows_the_caller_policy(leaf):
    import concurrent.futures

    class Loop:
        def run_in_executor(self, _ex, fn, *a):
            f = concurrent.futures.Future()
            f.set_result(fn(*a))
            return f

    client = L.LeafClient(leaf.url, TOKEN)
    for gate, expect in (
        (L.ConfirmGate(CODE), 0),  # unconfirmed stranger: ignored
        (L.ConfirmGate.for_caller(OWNER, CODE, OWNERS), 1),  # owner
    ):
        call = FakeCall(Loop())
        L.install_stop_hook(call, client, gate)
        before = len(leaf.calls)
        call.on_user_transcript("stop!")
        assert len(leaf.calls) - before == expect
        assert call.events[-1]["kind"] == "stop" and call.events[-1].get("refused", False) is (expect == 0)
    gate = L.ConfirmGate(CODE)
    call = FakeCall(Loop())
    L.install_stop_hook(call, client, gate)
    gate.check(CODE)  # stranger confirmed mid-call
    before = len(leaf.calls)
    call.on_user_transcript("leaf stop")
    assert len(leaf.calls) - before == 1


def test_prompt_and_greeting_adapt_to_the_owner(monkeypatch):
    monkeypatch.setenv("OWNER_NAME", "Cagatay")
    p_owner, p_stranger = L.leaf_prompt(True, owner_call=True), L.leaf_prompt(True)
    assert "never ask him for a confirmation key" in p_owner and "Cagatay" in p_owner
    assert "must give the confirmation key" in p_stranger and "even stopping" in p_stranger
    assert "never ask him" not in p_stranger and "Cagatay" not in p_stranger.split("line (")[1].split(")")[1]
    assert "Cagatay" in L.greeting(True) and "do not know this caller" in L.greeting(False)
    for p in (p_owner, p_stranger):
        assert "{" not in p and OWNER not in p


def test_make_agent_reads_the_invite_caller(monkeypatch):
    from strands_phone import agent as A

    monkeypatch.setenv("PHONE_PERSONA", "leaf")
    monkeypatch.setenv("MODEL_PROVIDER", "nova")
    monkeypatch.setenv("LEAF_PHONE_CONFIRM_CODE", CODE)
    monkeypatch.setenv("LEAF_PHONE_OWNER_NUMBERS", OWNER)
    for number, owner in ((OWNER, True), ("+15550009999", False), (None, False)):
        call = FakeCall()
        call.caller_number = number
        ag = A.make_agent(call, inbound=True)
        assert call.leaf_gate.owner is owner and call.leaf_gate.unlocked is owner
        assert ("never ask him" in ag.system_prompt) is owner
        assert ("your owner" in call.greeting) is owner
    call = FakeCall()
    call.caller_number = OWNER
    A.make_agent(call, inbound=False)  # outbound: the far end is never trusted by number
    assert not call.leaf_gate.owner


class ScriptedOwnerAgent(ScriptedLeafAgent):
    SCRIPT = [
        ("user", "hey leaf, walk three steps"),
        ("tool", "walk", {"steps": 3}),  # no key
        ("tool", "run_behavior", {"behavior": "wave"}),
        ("user", "stop!"),
        ("tool", "stop_moving", {}),
        ("tool", "hang_up", {}),
    ]


class ScriptedStrangerNoKey(ScriptedLeafAgent):
    SCRIPT = [
        ("user", "walk three steps"),
        ("tool", "walk", {"steps": 3}),
        ("user", "stop!"),
        ("tool", "stop_moving", {}),
        ("tool", "hang_up", {}),
    ]


@pytest.mark.parametrize(
    "agent_cls,from_number,ports",
    [
        (ScriptedOwnerAgent, OWNER, (16260, 16270, 16262, 16272)),
        (ScriptedStrangerNoKey, "+15550009999", (16360, 16370, 16362, 16372)),
        (ScriptedStrangerNoKey, "anonymous", (16460, 16470, 16462, 16472)),
    ],
)
def test_scripted_sip_call_caller_id_policy(tmp_path, leaf, agent_cls, from_number, ports):
    callee, caller, a = _scripted_call(tmp_path, leaf.url, TOKEN, CODE, ports, from_number=from_number, cls=agent_cls)
    res = {}
    for name, out in a.results:
        res.setdefault(name, []).append(out)
    posts = [p for m, p in leaf.paths() if m == "POST"]
    assert callee.end_reason == "agent hung up"
    assert all(OWNER not in json.dumps(e) for e in callee.events)  # the number is redacted in the call log
    if agent_cls is ScriptedOwnerAgent:
        assert a.gate.owner and res["walk"][0]["walked_m"] == 0.75 and res["stop_moving"][0]["status"] == "success"
        assert posts.count("/api/robot/walk") == 1 and posts.count("/api/robot/stop") == 2  # hook + tool
    else:
        assert not a.gate.owner and res["walk"][0] == L.GATE_MSG and res["stop_moving"][0] == L.GATE_MSG
        assert posts == [] and leaf.calls == []
        assert [e for e in callee.events if e["kind"] == "stop"][0]["refused"] is True
