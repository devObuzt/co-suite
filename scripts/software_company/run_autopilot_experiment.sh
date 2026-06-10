#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/wisamsholy/Documents/GitHub/Claudeai/oneshare"

cd "$ROOT_DIR"

set -a
source "$ROOT_DIR/api/.env"
set +a

python3 -u "$ROOT_DIR/scripts/software_company/autonomous_runner.py" \
  cosuite \
  --loop \
  --max-cycles 48 \
  --interval-minutes 10 \
  --execute-codex \
  --telegram \
  --timeout-minutes 45
