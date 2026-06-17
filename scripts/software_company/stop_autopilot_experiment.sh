#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$ROOT_DIR/reports/autopilot-experiment.pid"
SCREEN_NAME="oneshare-autopilot-8h"
LOCK_FILE="$ROOT_DIR/docs/software-company/projects/cosuite/.autonomous-runner.lock"

screen_list="$(/usr/bin/screen -ls 2>/dev/null || true)"
if grep -q "$SCREEN_NAME" <<<"$screen_list"; then
  /usr/bin/screen -S "$SCREEN_NAME" -X quit
  echo "Stopped autopilot experiment screen session $SCREEN_NAME"
fi

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if ps -p "$pid" >/dev/null 2>&1; then
    kill "$pid"
    echo "Stopped autopilot experiment PID $pid"
  else
    echo "Autopilot experiment PID $pid is not running."
  fi
fi

rm -f "$PID_FILE"
rm -f "$LOCK_FILE"
