"""Settings, all from the environment so the same code runs anywhere."""

from __future__ import annotations

import os

VC_HOST = os.environ.get("VC_HOST", "")  # e.g. abc123.voiceconnector.chime.aws
CALLER_ID = os.environ.get("CALLER_ID", "")  # E.164 number assigned to the Voice Connector
PUBLIC_IP = os.environ.get("PUBLIC_IP", "")  # the address Chime sends SIP and RTP to
SIP_PORT = int(os.environ.get("SIP_PORT", "5060"))
RTP_PORT = int(os.environ.get("RTP_PORT", "10000"))
MAX_CALL_S = int(os.environ.get("MAX_CALL_S", "600"))
FRAME = 160  # samples per 20 ms at 8 kHz
