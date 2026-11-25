#!/usr/bin/env bash
# Run ON the Surface, as your user, from the deploy/ folder. No sudo needed.
set -euo pipefail
mkdir -p ~/.config/autostart
cp "$(dirname "$0")/surface-kiosk.desktop" ~/.config/autostart/jarvis-kiosk.desktop
# keep the screen on while plugged in, never auto-lock
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
echo "kiosk autostart installed. Enable auto-login (needs sudo, see plan Task 8), then reboot."
