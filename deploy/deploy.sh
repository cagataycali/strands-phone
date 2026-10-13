#!/usr/bin/env bash
# Ship this checkout to the phone host and (re)start the answering service.
#   deploy/deploy.sh            # uses .state.env written by infra/up.sh
set -euo pipefail
cd "$(dirname "$0")/.."
. ./.state.env
SSH="ssh -o ConnectTimeout=10 -i $KEY ubuntu@$PUBLIC_IP"
rsync -az --delete -e "ssh -i $KEY" --exclude .venv --exclude .git --exclude calls --exclude '.state.env' --exclude '.secrets.env' ./ "ubuntu@$PUBLIC_IP:strands-phone/"
# optional .secrets.env (gitignored): MODEL_PROVIDER=openai, OPENAI_API_KEY=... -> root-only /etc/strands-phone.env
[ -f .secrets.env ] && scp -q -i "$KEY" .secrets.env "ubuntu@$PUBLIC_IP:.strands-phone.secrets"
$SSH bash -s <<REMOTE
set -euo pipefail
test -x ~/.local/bin/uv || curl -LsSf https://astral.sh/uv/install.sh | sh
test -d ~/venv || ~/.local/bin/uv venv -q -p 3.12 ~/venv
~/.local/bin/uv pip install -q -p ~/venv/bin/python -e '/home/ubuntu/strands-phone[openai]'
{ printf 'VC_HOST=%s\nCALLER_ID=%s\nPUBLIC_IP=%s\nAWS_REGION=%s\nSIP_ALLOW=%s\n' "$VC_HOST" "$NUMBER" "$PUBLIC_IP" "$REGION" "${SIP_ALLOW:-}"; cat ~/.strands-phone.secrets 2>/dev/null || true; } | sudo tee /etc/strands-phone.env >/dev/null
sudo chmod 600 /etc/strands-phone.env; rm -f ~/.strands-phone.secrets
sudo cp ~/strands-phone/deploy/strands-phone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable -q strands-phone
sudo systemctl restart strands-phone
sleep 2; systemctl is-active strands-phone
REMOTE
