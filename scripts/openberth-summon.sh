#!/usr/bin/env bash
# Bind this to a KDE global shortcut (System Settings > Shortcuts > Custom
# Shortcuts > New > Global Shortcut > Command/URL). GApplication's D-Bus
# single-instance activation means running this while OpenBerth is already
# open just raises/focuses the existing window instead of opening a new one.
set -euo pipefail

if command -v openberth-ui >/dev/null 2>&1; then
    openberth-ui "$@" &
else
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$repo_root"
    /usr/bin/python3 -m openberth.ui_app "$@" &
fi

sleep 0.3
wmctrl -a OpenBerth 2>/dev/null
