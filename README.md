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

## LEAF: call a robot

`PHONE_PERSONA=leaf` makes the line answer as LEAF, a Fauna Sprout humanoid, in the first person
([strands_phone/leaf.py](strands_phone/leaf.py)). Its tools (state, look, modes, behaviours, walk, turn) call the LEAF
dashboard at `LEAF_URL` with a scoped `LEAF_PHONE_TOKEN` that the dashboard only accepts on those routes and STOP.

- **Caller ID policy.** A call from a number in `LEAF_PHONE_OWNER_NUMBERS` (comma list, any format, normalised to
  E.164; set it in the host env, never in git) is the owner: every robot tool works with no key, `confirm` says it is
  not needed, and stop works. Every other caller, including a withheld number, is a stranger.
- For a stranger every robot tool answers "please provide a confirmation key" until `confirm(code)` matches
  `LEAF_PHONE_CONFIRM_CODE` in this call. Three wrong keys lock confirm for the rest of the call. The key is never logged.
- A stranger can't stop the robot either, by `stop_moving` or by saying "stop", until they confirm. Once they have,
  a spoken "stop" stops the robot before the model hears it. `hang_up` always works.
- **Caller ID is spoofable.** Anyone who can send a call with the owner's number in the SIP From header gets the
  owner's access. It saves the owner typing a key on his own phone. It is not authentication. Leave
  `LEAF_PHONE_OWNER_NUMBERS` empty if that risk is not acceptable.
- There is no damp tool. Unset `PHONE_PERSONA` (or `default`) and redeploy to get the plain agent back.

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
