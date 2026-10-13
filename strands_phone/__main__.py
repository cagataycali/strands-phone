"""strands-phone answer | strands-phone call +15551234567"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from .call import Call, InboundCall
from .config import CALLER_ID, PUBLIC_IP, VC_HOST


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG", "INFO"), format="%(message)s")
    logging.getLogger("strands").setLevel(logging.WARNING)
    missing = [k for k, v in {"VC_HOST": VC_HOST, "CALLER_ID": CALLER_ID, "PUBLIC_IP": PUBLIC_IP}.items() if not v]
    if missing:
        sys.exit(f"set {', '.join(missing)} (see .env.example)")
    if len(sys.argv) == 2 and sys.argv[1] == "answer":
        call: Call = InboundCall()
    elif len(sys.argv) == 3 and sys.argv[1] == "call":
        call = Call(sys.argv[2])
    else:
        sys.exit("usage: strands-phone call +1NXXNXXXXXX | strands-phone answer")
    await call.run()
    print(json.dumps({"reason": call.end_reason, "events": len(call.events)}))


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
