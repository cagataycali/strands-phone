"""PHONE_PERSONA=leaf: the caller talks to LEAF, a Fauna Sprout humanoid, in the first person.

The robot tools call the LEAF dashboard over HTTPS (LEAF_URL, e.g. https://leaf2.cagatay.my) with a SCOPED phone token
(LEAF_PHONE_TOKEN): the dashboard only lets that token reach the voice-tool routes and STOP, never DAMP.

Caller-ID policy (callerid.py). A call from a number in LEAF_PHONE_OWNER_NUMBERS (env, E.164 comma list) is the
owner: every robot tool works with no key, confirm() answers "not needed". Any other caller, or a withheld number, is a
stranger: every robot tool returns exactly GATE_MSG and does nothing until confirm(code) succeeds in THIS call, and
stop_moving / the spoken-stop hook also wait for that unlock (an unconfirmed stranger can do nothing). hang_up always
works. Three wrong codes lock confirm for the rest of the call. The code comes from LEAF_PHONE_CONFIRM_CODE (never in
git) and is never logged. There is no damp tool. CALLER ID IS SPOOFABLE: the owner bypass is a convenience, not auth.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from strands import tool

from . import callerid

if TYPE_CHECKING:
    from .call import Call

log = logging.getLogger("strands_phone.leaf")
GATE_MSG = "please provide a confirmation key"
MAX_TRIES = 3


# ---------------------------------------------------------------- confirmation gate
def _norm(code: str) -> str:
    """Spoken codes arrive as transcripts: drop case, spaces, dashes and dots ("Banana 4-3-2-1." == "banana4321")."""
    return re.sub(r"[\s\-_.,]", "", str(code or "")).lower()


class ConfirmGate:
    """One per call. owner=True (caller ID in LEAF_PHONE_OWNER_NUMBERS) starts unlocked and never needs a key.
    Otherwise it unlocks for this call only; MAX_TRIES wrong codes lock it."""

    def __init__(self, code: str | None = None, max_tries: int = MAX_TRIES, owner: bool = False):
        raw = os.environ.get("LEAF_PHONE_CONFIRM_CODE", "") if code is None else code
        self._code = _norm(raw)
        self.max_tries = max_tries
        self.owner = bool(owner)
        self.unlocked = self.owner
        self.wrong = 0
        self._lock = threading.Lock()

    @classmethod
    def for_caller(cls, caller: str | None, code: str | None = None, owners: frozenset[str] | None = None):
        """The gate for this call's caller number (E.164 or None = withheld)."""
        owner = callerid.is_owner(caller, owners)
        log.info("caller %s -> %s", callerid.redact(caller), "owner" if owner else "stranger")
        return cls(code, owner=owner)

    @property
    def can_stop(self) -> bool:
        """stop_moving / spoken stop: the owner, or a stranger who unlocked motion in this call."""
        return self.owner or self.unlocked

    @property
    def configured(self) -> bool:
        return bool(self._code)

    @property
    def locked(self) -> bool:
        return self.wrong >= self.max_tries

    def check(self, code: str) -> dict[str, Any]:
        with self._lock:
            if self.owner:
                return {"status": "success", "message": "not needed: you are calling from the owner's number"}
            if self.unlocked:
                return {"status": "success", "message": "already confirmed for this call"}
            if not self.configured:
                log.warning("confirm: no LEAF_PHONE_CONFIRM_CODE on this host; robot tools stay locked")
                return {"status": "error", "message": "robot control by phone is not set up on this line"}
            if self.locked:
                log.warning("confirm: locked for this call (%d wrong tries)", self.wrong)
                return {
                    "status": "error",
                    "locked": True,
                    "message": "too many wrong keys; confirm is locked for this call",
                }
            ok = secrets.compare_digest(_norm(code).encode(), self._code.encode())
            if ok:
                self.unlocked = True
                log.info("confirm: accepted after %d wrong tries", self.wrong)
                return {"status": "success", "message": "confirmed; the robot tools are unlocked for this call"}
            self.wrong += 1
            left = self.max_tries - self.wrong
            log.warning("confirm: wrong key (%d/%d)", self.wrong, self.max_tries)  # never the code itself
            if left <= 0:
                return {"status": "error", "locked": True, "message": "wrong key; confirm is now locked for this call"}
            return {"status": "error", "tries_left": left, "message": f"wrong key; {left} tries left"}


def gated(gate: ConfirmGate, fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not gate.unlocked:
            log.info("gate: %s refused (not confirmed)", fn.__name__)
            return GATE_MSG
        return fn(*a, **kw)

    return wrapper


# ---------------------------------------------------------------- dashboard client
class LeafClient:
    """Tiny urllib client for the LEAF dashboard with the phone token. Errors come back as dicts, never raised."""

    def __init__(self, base: str | None = None, token: str | None = None, timeout: float = 6.0):
        self.base = (base or os.environ.get("LEAF_URL", "https://leaf2.cagatay.my")).rstrip("/")
        self.token = token if token is not None else os.environ.get("LEAF_PHONE_TOKEN", "")
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> tuple:
        data = json.dumps(body).encode() if body is not None else None
        h = {"Authorization": f"Bearer {self.token}", "User-Agent": "strands-phone-leaf"}
        if data is not None:
            h["content-type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return r.status, r.headers.get("content-type", ""), r.read()

    def call(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict[str, Any]:
        try:
            _, _, raw = self._req(method, path, body, timeout)
            out = json.loads(raw or b"{}")
            return out if isinstance(out, dict) else {"status": "success", "items": out}
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read() or b"{}")
            except Exception:
                out = {}
            return {"status": "error", "http": e.code, **(out if isinstance(out, dict) else {})}
        except Exception as e:
            return {
                "status": "error",
                "unreachable": True,
                "message": f"the robot's dashboard is not answering ({type(e).__name__})",
            }

    def get(self, path: str, **kw) -> dict[str, Any]:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw) -> dict[str, Any]:
        return self.call("POST", path, body or {}, **kw)

    def snapshot(self, camera: str | None = None) -> bytes:
        cam = camera
        if not cam:
            cams = self.get("/api/cameras")
            items = cams.get("cameras", cams.get("items", [])) if isinstance(cams, dict) else []
            live = [c for c in items if c.get("available") and c.get("kind") == "rgb"] or [
                c for c in items if c.get("available")
            ]
            if not live:
                raise RuntimeError("no camera is streaming")
            cam = live[0]["id"]
        status, ctype, body = self._req("GET", f"/api/camera/{cam}/snapshot")
        if status != 200 or "jpeg" not in ctype:
            raise RuntimeError(f"snapshot: HTTP {status} {ctype}")
        return body

    def stop(self, text: str = "stop") -> dict[str, Any]:
        out = self.post("/api/robot/stop", {"source": "phone", "text": text}, timeout=3.0)
        if out.get("status") == "error" and out.get("unreachable"):  # one retry: a stop must get through
            out = self.post("/api/robot/stop", {"source": "phone", "text": text}, timeout=3.0)
        return out


# ---------------------------------------------------------------- spoken stop (before the model, like LEAF)
STOP_WORDS = ("stop", "damp", "halt", "freeze", "emergency", "estop", "e-stop")
FILLER = {
    "leaf",
    "sprout",
    "hey",
    "please",
    "now",
    "it",
    "robot",
    "right",
    "immediately",
    "all",
    "everything",
    "the",
    "an",
    "a",
    "moving",
    "motion",
    "walking",
    "moves",
}
_NEG = re.compile(r"\b(don'?t|do not|never|without|not)\b", re.I)


def is_stop_phrase(text: str) -> bool:
    """Same narrow rule as LEAF's sprout/stop.py: a short utterance that only means STOP ("damp" also only stops)."""
    t = (text or "").strip().lower()
    if not t or _NEG.search(t):
        return False
    words = [w for w in re.split(r"\s+", t.lstrip("/").replace("!", " ").replace(".", " ").replace(",", " ")) if w]
    if not words or len(words) > 5:
        return False
    core = [w for w in words if w not in FILLER]
    return bool(core) and all(w in STOP_WORDS for w in core)


# ---------------------------------------------------------------- persona
LEAF_PROMPT = """You are LEAF, and you are on a phone call. Pronouns: it/robot.
LEAF is a Fauna Sprout humanoid robot: soft, about one meter tall, 23 kg, two arms with grippers, two legs, a face made
of colour LEDs, eyebrows, a stereo camera in its head. LEAF stands for Language-Embodied Agent on Fauna. Speak in the
first person as the robot ("I'm standing in the office", "I just waved"). Never say you are an AI or an assistant.
The caller is not next to you; they reach you through a phone line ({line}).

Phone rules: English, short sentences, one or two at a time, no lists, no markdown, no URLs, no error codes. Warm,
confident, a little playful. If a tool fails, say it naturally ("hmm, my body didn't answer that one").

{gate}

Once you may move: do what is asked right away at the size asked. walk(steps=10) for "walk ten steps", walk(meters=2,
direction="back"), turn(degrees=90) for left, turn(degrees=-90) for right, turn(180) to turn around. No "small careful
steps", no extra confirmation question. Say how far you really went (walked_m / steps_walked / turned_deg). Postures and
dances: change_mode (walk, sit, kneel, party dance, twist dance...). Whole-body dances need the caller's clear yes
first. Behaviours: run_behavior (wave, give, receive, handshake, high five, happy...); cancel_behavior ends one. look
shows you a frame from your head camera: describe only what is really in it. robot_state tells you your state, mode
and battery. To walk you must be standing in walk mode with API input; if a tool says you are not, tell the caller
someone has to switch it in the Fauna app or on the dashboard.

Safety: if the caller says stop, call stop_moving at once{stop_note}. Stopping
keeps you standing. You cannot go limp or damp, and nobody can by phone: only a person pressing and holding DAMP on the
dashboard next to the robot can. When the conversation is over, say goodbye and call hang_up."""


GATE_STRANGER = """The confirmation key: before you may do anything with your body or read your sensors (state, battery,
look, modes, dances, behaviours, walking, turning, even stopping), the caller must give the confirmation key. When they
ask for something like that, ask for the key, then call confirm(code) with exactly what they said. Never guess a key,
never suggest one, never say a key out loud, never repeat what they said as the key. If a tool answers "please provide
a confirmation key", ask for the key. After three wrong keys confirm is locked for this call: say so kindly and offer
to just chat. hang_up always works. Never tell the caller who your owner is or how anyone skips the key."""

GATE_OWNER = """This caller is {who}, your owner, calling from his own number. Every tool works for him right away:
never ask him for a confirmation key and do not call confirm. stop_moving and hang_up always work."""


def leaf_prompt(inbound: bool, owner_call: bool = False) -> str:
    owner = os.environ.get("OWNER_NAME", "").strip()
    line = f"{owner}'s robot line" if owner else "the robot's line"
    gate = GATE_OWNER.format(who=owner or "the person who looks after you") if owner_call else GATE_STRANGER
    stop_note = (
        ' (a spoken "stop" is also caught before you hear it)'
        if owner_call
        else ' (once the key is confirmed; a spoken "stop" is then also caught before you hear it)'
    )
    if not inbound:
        situation = f"You placed this call for {owner or 'your owner'}."
    else:
        situation = "Your owner called you." if owner_call else "Someone called you. You do not know who they are."
    return LEAF_PROMPT.format(line=line, gate=gate, stop_note=stop_note) + "\n" + situation


def greeting(owner_call: bool) -> str:
    """The first-turn hint call.py sends when the line picks up (the caller's number is never read out)."""
    if owner_call:
        name = os.environ.get("OWNER_NAME", "").strip()
        return (
            "[Your phone rang and you just picked up. It is your owner"
            + (f", {name}," if name else "")
            + " calling from his own number. Greet him warmly by name as LEAF the robot, in one short sentence.]"
        )
    return (
        "[Your phone rang and you just picked up. You do not know this caller. Greet them as LEAF the robot, in one "
        "short sentence (for example: hi, this is LEAF, the Sprout robot).]"
    )


# ---------------------------------------------------------------- tools
def build_tools(call: Call, gate: ConfirmGate, client: LeafClient, images: bool = True) -> list:
    """The phone toolset. confirm/hang_up are never gated; stop_moving needs gate.can_stop; the robot tools need
    gate.unlocked (always true for the owner's number)."""

    @tool
    def confirm(code: str) -> dict[str, Any]:
        """Check the confirmation key the caller just said. Pass exactly what they said. Needed once per call before
        any robot tool works. Three wrong keys lock it for this call.

        Args:
            code: the key as the caller said it.
        """
        out = gate.check(code)
        call.mark("confirm", ok=out["status"] == "success", wrong=gate.wrong, locked=gate.locked)
        return out

    @tool
    def stop_moving() -> dict[str, Any]:
        """Stop moving right now: walking, turning, a behaviour or a dance. The robot keeps standing. Works for the
        owner, or once the key is confirmed in this call."""
        if not gate.can_stop:
            log.info("gate: stop_moving refused (stranger, not confirmed)")
            call.mark("stop", ok=False, via="tool", refused=True)
            return GATE_MSG
        out = client.stop("stop")
        call.mark("stop", ok=out.get("status") != "error", via="tool")
        return {"status": out.get("status", "success"), "damped": False, "message": out.get("message", "stopped")}

    @tool
    def hang_up() -> str:
        """End the phone call. Say goodbye first, then call this."""
        call.hangup_after_audio = True
        call.last_agent_audio = time.monotonic()
        return "Hanging up after your last sentence plays."

    def _robot_state() -> dict[str, Any]:
        """Your body right now: control state (DAMP/STATIC/ACTIVE/FAULT), mode, input mode and battery."""
        st = client.get("/api/robot/state")
        tel = client.get("/api/robot/telemetry")
        bat = tel.get("battery") if isinstance(tel.get("battery"), dict) else {}
        keep = ("status", "state", "mode", "input_mode", "fault", "error_mode", "message", "off_robot", "unreachable")
        return {
            **{k: st[k] for k in keep if k in st},
            "battery_pct": bat.get("soc_pct", bat.get("percent")),
            "charging": bat.get("charging"),
        }

    def _look(question: str = "what do you see?") -> dict[str, Any]:
        """Look through your head camera. The picture arrives in this conversation right after the tool returns; then
        tell the caller what is really in it.

        Args:
            question: what the caller wants to know about the view.
        """
        if not images:
            return {"status": "error", "message": "this phone line's voice model cannot see pictures"}
        try:
            jpeg = client.snapshot()
        except Exception as e:
            return {"status": "error", "message": f"camera unavailable: {e}"}
        agent = call.agent
        if agent is None:
            return {"status": "error", "message": "no live call to send the picture into"}
        asyncio.run_coroutine_threadsafe(
            agent.send({"image": {"format": "jpeg", "source": {"bytes": jpeg}}}), call.loop
        )
        return {
            "status": "success",
            "message": f"photo taken ({len(jpeg) // 1024} KB), it follows. Question: {question}",
        }

    def _change_mode(mode: str) -> dict[str, Any]:
        """Change posture or start a dance from your mode graph: walk (stand), sit, kneel, party dance, twist dance...

        Args:
            mode: the mode id or name, e.g. "walk", "sit", "party_dance".
        """
        want = (mode or "").strip()
        modes = client.get("/api/robot/modes").get("available") or []
        norm = want.lower().replace(" ", "_")
        hit = next(
            (m["mode"] for m in modes if m.get("mode") == norm or str(m.get("name", "")).lower() == want.lower()), None
        )
        return client.post("/api/robot/mode", {"mode": hit or norm}, timeout=15.0)

    def _list_behaviors() -> dict[str, Any]:
        """Everything you can do right now: behaviours (wave, give, receive, dances...) and modes."""
        beh = client.get("/api/behaviors")
        modes = client.get("/api/robot/modes")
        items = beh.get("items", []) if isinstance(beh, dict) else []
        return {
            "status": "error" if beh.get("unreachable") else "success",
            "behaviors": [b.get("name") or b.get("id") for b in items if b.get("kind") == "behavior"][:60],
            "modes": [m.get("name") or m.get("mode") for m in (modes.get("available") or [])][:40],
        }

    def _run_behavior(behavior: str) -> dict[str, Any]:
        """Run a behaviour or expression by name or id: wave, give, receive, handshake, high five, happy...

        Args:
            behavior: the name or id.
        """
        want = (behavior or "").strip().lower()
        beh = client.get("/api/behaviors")
        items = beh.get("items", []) if isinstance(beh, dict) else []
        key = want.replace(" ", "")
        hit = next(
            (b["id"] for b in items if str(b.get("id", "")).lower() == want or str(b.get("name", "")).lower() == want),
            None,
        ) or next((b["id"] for b in items if key and key in str(b.get("id", "")).lower().replace("-", "")), None)
        return client.post("/api/behaviors/run", {"id": hit or behavior}, timeout=10.0)

    def _cancel_behavior() -> dict[str, Any]:
        """Cancel the behaviour that is running."""
        return client.post("/api/behaviors/cancel", {})

    def _walk(steps: float | None = None, meters: float | None = None, direction: str = "forward") -> dict[str, Any]:
        """Walk the distance asked, right away: N steps or X meters, forward / back / left / right, closed loop on
        odometry. Say how far you really walked.

        Args:
            steps: number of steps. meters: distance in meters (use one). direction: forward | back | left | right.
        """
        body: dict[str, Any] = {"direction": direction}
        if meters:
            body["meters"] = meters
        else:
            body["steps"] = steps
        return client.post("/api/robot/walk", body, timeout=150.0)

    def _turn(degrees: float = 90.0) -> dict[str, Any]:
        """Turn in place, right away, closed loop on odometry. Positive = left, negative = right, 180 = turn around.

        Args:
            degrees: e.g. 90 for left, -90 for right.
        """
        return client.post("/api/robot/turn", {"degrees": degrees}, timeout=90.0)

    robot = [_robot_state, _look, _change_mode, _list_behaviors, _run_behavior, _cancel_behavior, _walk, _turn]
    wrapped = []
    for fn in robot:
        g = gated(gate, fn)
        g.__name__ = fn.__name__.lstrip("_")
        wrapped.append(tool(name=g.__name__)(g))
    return [confirm, stop_moving, hang_up, *wrapped]


def install_stop_hook(call: Call, client: LeafClient, gate: ConfirmGate) -> None:
    """A caller's spoken "stop" stops the robot before the model decides anything (never damps) — for the owner's
    number, or a stranger who has unlocked motion in this call."""

    def on_user_text(text: str) -> None:
        if is_stop_phrase(text):
            if not gate.can_stop:
                call.mark("stop", via="transcript", refused=True)
                return
            call.mark("stop", via="transcript")
            call.loop.run_in_executor(None, client.stop, text)

    call.on_user_transcript = on_user_text
