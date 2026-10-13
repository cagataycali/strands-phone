<div align="center">

# strands-phone

**Call your agent.**

Experimental: A real phone number that rings a Strands `BidiAgent`, on Nova 2 Sonic or gpt-realtime-2.

[Docs](https://cagataycali.github.io/strands-phone/) ·
[Quickstart](https://cagataycali.github.io/strands-phone/quickstart/) ·
[How it works](https://cagataycali.github.io/strands-phone/how-it-works/) ·
[Design](https://cagataycali.github.io/strands-phone/design/)

</div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/drawings/p01_call_path.dark.svg">
  <img alt="A phone call through the Chime SDK Voice Connector and strands-phone into a BidiAgent and back" src="docs/assets/drawings/p01_call_path.paper.svg" width="100%">
</picture>

## Run it

```bash
infra/up.sh        # phone number, Voice Connector, EC2
deploy/deploy.sh   # starts the service that answers calls
```

Dial the `NUMBER` from `.state.env`. To have the agent dial you instead, run this on the host:

```bash
set -a; . /etc/strands-phone.env; set +a
~/venv/bin/strands-phone call +15551234567
```

`infra/down.sh` deletes everything and releases the number.

## One call

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/drawings/p02_one_call.dark.svg">
  <img alt="SIP ladder of one inbound call: INVITE, 100, 180 with the model opening, 200, ACK, RTP both ways, BYE" src="docs/assets/drawings/p02_one_call.paper.svg" width="100%">
</picture>

## The audio bridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/drawings/p03_audio_bridge.dark.svg">
  <img alt="Caller audio straight into the agent; agent audio paced onto the line by a 20 ms clock; barge-in clears the buffer" src="docs/assets/drawings/p03_audio_bridge.paper.svg" width="100%">
</picture>

## Models

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/drawings/p04_auth.dark.svg">
  <img alt="Nova Sonic signs with the instance role; gpt-realtime-2 reads its key from a root-only file" src="docs/assets/drawings/p04_auth.paper.svg" width="100%">
</picture>

| `MODEL_PROVIDER` | Model | Auth |
|---|---|---|
| `nova` (default) | Amazon Nova 2 Sonic | EC2 instance role |
| `openai` | OpenAI gpt-realtime-2 | `OPENAI_API_KEY` |

Put `MODEL_PROVIDER=openai` and `OPENAI_API_KEY` in `.secrets.env` (gitignored), then run `deploy/deploy.sh`.

## Design

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/drawings/p05_design.dark.svg">
  <img alt="What runs where: Voice Connector, one EC2 host running strands-phone, the BidiAgent and the two models" src="docs/assets/drawings/p05_design.paper.svg" width="100%">
</picture>

## Test

```bash
uv venv -p 3.12 && uv pip install -e '.[dev,openai]' && .venv/bin/pytest -q
```

## Contributing, security, license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Licensed under [Apache 2.0](LICENSE).
Built with [Strands Agents](https://strandsagents.com/); not an official AWS project.
