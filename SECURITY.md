# Security

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button (Security → Advisories) on
this repository, not in a public issue. We aim to reply within 5 business days.

## What to know before you deploy

- **SIP and RTP are unencrypted** (the Voice Connector runs with `--no-require-encryption`). Two things scope them:
  the security group allows only Chime SDK's documented signalling and media ranges, and `SIP_ALLOW` drops any
  other source in code. Termination (outbound calls) is restricted to the host's Elastic IP.
- **Secrets:** AWS uses the EC2 instance role, so no keys sit on disk. `OPENAI_API_KEY` goes in `.secrets.env`
  locally (gitignored). On the host it lives in `/etc/strands-phone.env`, mode 600, owned by root. Never commit
  either file.
- **Call content:** transcripts are logged to the systemd journal. Recordings (`calls/*.wav` + `.json`) are written
  only with `RECORD_CALLS=1`. Check the consent laws where you and your callers are before turning it on.
- **Cost:** a claimed number, an EC2 instance and an Elastic IP bill while idle, and each call bills per minute.
  `infra/down.sh` removes all of it.
- **The agent can hang up** and has a `current_time` tool. Any tool you add can be invoked by anyone who calls the
  number, so treat tools as public endpoints.
