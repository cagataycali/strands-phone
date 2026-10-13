"""The agent on the line: Nova 2 Sonic at the phone's own 8 kHz, plus two tools."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

from strands import tool
from strands.bidi import BidiAgent
from strands.bidi.models import BedrockNovaSonicModel, BidiModel

if TYPE_CHECKING:
    from .call import Call


def make_model() -> BidiModel:
    """MODEL_PROVIDER=nova (default, Bedrock, 8 kHz native) or openai (Realtime, 24 kHz, resampled in call.py)."""
    provider = os.environ.get("MODEL_PROVIDER", "nova").lower()
    if provider == "openai":
        from strands.bidi.models import OpenAIRealtimeModel

        return OpenAIRealtimeModel(
            model_id=os.environ.get("OPENAI_MODEL", "gpt-realtime-2"),
            transcription_model_id=os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
            voice=os.environ.get("VOICE", "marin"),
        )  # api key: OPENAI_API_KEY
    if provider != "nova":
        raise ValueError(f"MODEL_PROVIDER={provider!r}: expected nova or openai")
    return BedrockNovaSonicModel(
        model_id=os.environ.get("NOVA_MODEL", "amazon.nova-2-sonic-v1:0"),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        audio={"input": {"sample_rate": 8000}, "output": {"sample_rate": 8000}},
        voice=os.environ.get("VOICE", "matthew"),
    )


def default_prompt(model_id: str, inbound: bool) -> str:
    """The phone persona. Set SYSTEM_PROMPT to replace it, or OWNER_NAME to say whose line this is."""
    owner = os.environ.get("OWNER_NAME", "").strip()
    whose = f"{owner}'s" if owner else "this"
    situation = (
        f"Someone called {whose} phone number and you answered."
        if inbound
        else f"You placed this call on behalf of {owner or 'the owner of this line'}."
    )
    return (
        f"You are a Strands agent on a real phone call, running on {model_id} "
        f"through an Amazon Chime SDK Voice Connector. {situation} "
        "Speak like a person on the phone: short sentences, no lists, no markdown. "
        "If asked what you can do, say you can tell the time and hang up. "
        "When the conversation is over, say goodbye and call hang_up. "
        "If you reach a voicemail greeting or a beep, leave one short sentence saying you will call back, "
        "then call hang_up."
    )


def make_agent(call: Call, inbound: bool = False) -> BidiAgent:
    @tool
    def current_time() -> str:
        """The current date and time where this line lives (TIMEZONE, default UTC)."""
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(os.environ.get("TIMEZONE", "UTC"))).strftime("%A %B %d, %I:%M %p")

    @tool
    def hang_up() -> str:
        """End the phone call. Say goodbye first, then call this."""
        call.hangup_after_audio = True
        call.last_agent_audio = time.monotonic()
        return "Hanging up after your last sentence plays."

    model = make_model()
    return BidiAgent(
        model=model,
        tools=[current_time, hang_up],
        system_prompt=os.environ.get("SYSTEM_PROMPT") or default_prompt(model.model_id, inbound),
    )
