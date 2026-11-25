#!/usr/bin/env bash
# Copy the panel to the NUC and (re)build its Python environment. Run from jarvis-panel/ on the PC.
# Never touches /home/YOUR_USER/jarvis/secrets.toml.
set -euo pipefail
cd "$(dirname "$0")/.."
tar czf - --exclude='__pycache__' jarvis web config.toml run.py requirements.txt \
  | ssh nuc 'mkdir -p ~/jarvis && tar xzf - -C ~/jarvis'
ssh nuc 'cd ~/jarvis && { [ -d .venv ] || python3 -m venv .venv; } && .venv/bin/pip install -q -r requirements.txt'
echo "deployed. restart with: sudo systemctl restart jarvis"
