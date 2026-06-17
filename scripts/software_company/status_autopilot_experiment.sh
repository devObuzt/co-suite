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

screen_list="$(/usr/bin/screen -ls 2>/dev/null || true)"
if grep -q "$SCREEN_NAME" <<<"$screen_list"; then
  echo "Autopilot experiment running in screen session $SCREEN_NAME"
  screen_running=1
else
  echo "Autopilot experiment screen session is not running."
  screen_running=0
fi

if [[ "$screen_running" -eq 0 && -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if ps -p "$pid" >/dev/null 2>&1; then
    echo "Autopilot experiment running with PID $pid"
  else
    echo "Autopilot experiment PID file exists, but PID $pid is not running."
  fi
elif [[ "$screen_running" -eq 0 ]]; then
  echo "Autopilot experiment is not running."
fi

if [[ -f "$LOCK_FILE" ]]; then
  lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  echo "Runner lock exists: $LOCK_FILE PID=${lock_pid:-unknown}"
fi

echo "Out log: $OUT_LOG"
tail -20 "$OUT_LOG" 2>/dev/null || true
echo ""
echo "Err log: $ERR_LOG"
tail -20 "$ERR_LOG" 2>/dev/null || true
echo ""
echo "Screen log: $SCREEN_LOG"
tail -20 "$SCREEN_LOG" 2>/dev/null || true
