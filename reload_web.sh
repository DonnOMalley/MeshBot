#!/bin/bash
# Hot-reload the MeshBot web dashboard without restarting the radio/monitors.
# Only signals a bot that wrote data/meshbot.pid (i.e. one that handles SIGUSR1);
# older versions would be killed by SIGUSR1, so this refuses in that case.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
PID_FILE="data/meshbot.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "No $PID_FILE - the running MeshBot does not support hot reload (restart it once on the new code)." >&2
  exit 1
fi
PID=$(cat "$PID_FILE")
if ! [[ "$PID" =~ ^[0-9]+$ ]] || [ ! -r "/proc/$PID/cmdline" ] || ! tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null | grep -q "meshbot.py"; then
  echo "PID file is stale (process $PID is not MeshBot). Not sending anything." >&2
  exit 1
fi
kill -USR1 "$PID" && echo "Reload requested (PID $PID). Watch: tmux -L meshbot attach -t meshbot"
