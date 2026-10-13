# Quickstart

You need an AWS account with Chime SDK Voice and Bedrock (Nova 2 Sonic), the AWS CLI, and Python 3.12. It takes about five minutes.

## 1. Provision

```bash
git clone https://github.com/cagataycali/strands-phone && cd strands-phone
infra/up.sh --state NJ
```

This orders a local number and creates a Voice Connector, a t4g.small EC2 instance with an Elastic IP, a security group and the instance role. It writes the ids to `.state.env`. Running it again changes nothing that already exists. These resources cost money while they sit idle.

## 2. Deploy

```bash
deploy/deploy.sh
```

This copies the repo to the host, installs it, and starts the `strands-phone` systemd service. The service answers one call at a time and starts listening again as soon as a call ends.

## 3. Call it

Dial the `NUMBER` from `.state.env`. To have the agent dial out instead, run this on the host:

```bash
set -a; . /etc/strands-phone.env; set +a
~/venv/bin/strands-phone call +15551234567
```

With `RECORD_CALLS=1`, every call leaves `calls/<utc>.wav` (left channel: the other party, right channel: the agent) and a `.json` timeline.

## Configure

| Variable | Default | |
|---|---|---|
| `MODEL_PROVIDER` | `nova` | `nova` or `openai` |
| `NOVA_MODEL` | `amazon.nova-2-sonic-v1:0` | |
| `OPENAI_MODEL` | `gpt-realtime-2` | needs `OPENAI_API_KEY` |
| `VOICE` | `matthew` / `marin` | per provider |
| `MAX_CALL_S` | `600` | hard stop |
| `RECORD_CALLS` | off | `1` keeps `calls/<utc>.wav` + `.json`; check consent laws first |
| `SIP_ALLOW` | Chime CIDRs | comma-separated sources that may send SIP; empty accepts all |
| `OWNER_NAME`, `SYSTEM_PROMPT` | none | whose line it is; or replace the whole prompt |
| `TIMEZONE` | `UTC` | for the `current_time` tool |
| `VC_HOST`, `CALLER_ID`, `PUBLIC_IP` | from `.state.env` | written by `deploy.sh` |

Put secrets in `.secrets.env`. Git ignores it, and `deploy.sh` copies it into the host's root-only `/etc/strands-phone.env`.

## Tear down

```bash
infra/down.sh   # asks first, then deletes everything and releases the number
```
