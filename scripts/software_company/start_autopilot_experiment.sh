#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$ROOT_DIR/reports/autopilot-experiment.pid"
OUT_LOG="$ROOT_DIR/reports/autopilot-experiment.out.log"
ERR_LOG="$ROOT_DIR/reports/autopilot-experiment.err.log"
SCREEN_LOG="$ROOT_DIR/reports/autopilot-experiment.screen.log"
SCREEN_NAME="oneshare-autopilot-8h"
LOCK_FILE="$ROOT_DIR/docs/software-company/projects/cosuite/.autonomous-runner.lock"

mkdir -p "$ROOT_DIR/reports"

screen_list="$(/usr/bin/screen -ls 2>/dev/null || true)"
if grep -q "$SCREEN_NAME" <<<"$screen_list"; then
  echo "Autopilot experiment already running in screen session $SCREEN_NAME"
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE")"
  if ps -p "$existing_pid" >/dev/null 2>&1; then
    echo "Autopilot experiment already running with PID $existing_pid"
    exit 1
  fi
  rm -f "$PID_FILE"
fi

if [[ -f "$LOCK_FILE" ]]; then
  lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [[ -n "$lock_pid" ]] && ps -p "$lock_pid" >/dev/null 2>&1; then
    echo "Autonomous runner lock is active with PID $lock_pid"
    exit 1
  fi
  rm -f "$LOCK_FILE"
fi

cd "$ROOT_DIR"

/usr/bin/screen -L -dmS "$SCREEN_NAME" /bin/zsh -lc \
  "echo \$\$ > '$PID_FILE'; cd '$ROOT_DIR'; '$ROOT_DIR/scripts/software_company/run_autopilot_experiment.sh' >> '$OUT_LOG' 2>> '$ERR_LOG'"

echo "Autopilot experiment started in screen session $SCREEN_NAME"
echo "Screen log: $SCREEN_LOG"
echo "Out log: $OUT_LOG"
echo "Err log: $ERR_LOG"
