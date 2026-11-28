#!/bin/bash
# Install MeshBot as a systemd user service that starts at boot (no login needed).
# Run as the user that owns the checkout and the radio (must be in 'dialout').
# Re-run after moving the checkout; it is safe to run more than once.
set -euo pipefail

SERVICE_NAME="meshbot.service"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MESHBOT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$MESHBOT_DIR/.venv/bin/python"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [ ! -x "$PYTHON" ]; then
  echo "No virtualenv Python at $PYTHON - create .venv and install requirements.txt first." >&2
  exit 1
fi
if ! id -nG | grep -qw dialout; then
  echo "Warning: $(id -un) is not in the 'dialout' group, so the bot cannot open the radio." >&2
fi

mkdir -p "$UNIT_DIR"
sed -e "s|@MESHBOT_DIR@|$MESHBOT_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
  "$SCRIPT_DIR/$SERVICE_NAME" > "$UNIT_DIR/$SERVICE_NAME"
echo "Wrote $UNIT_DIR/$SERVICE_NAME"

# Lingering starts the user's systemd manager at boot, before anyone logs in.
if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "Enabling lingering for $(id -un) (may ask for your password)..."
  loginctl enable-linger "$(id -un)"
fi

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
echo
echo "Installed and enabled. MeshBot will start at every boot."
echo "  Start now:   systemctl --user start meshbot   (stop any copy running in a terminal first)"
echo "  Status:      systemctl --user status meshbot"
echo "  Logs:        journalctl --user -u meshbot -f   (also log/console_*.log and the Console page)"
echo "  Restart:     systemctl --user restart meshbot"
