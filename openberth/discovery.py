from __future__ import annotations

import subprocess

from openberth.models import DiscoveredTarget

# Ephemeral grouped-session views created by pop_out_docked() to give a
# popped-out TV its own independent "current window" when its real session
# already has another attached client. Never real TVs -- always filtered out.
EPHEMERAL_VIEW_PREFIX = "__openberth_view_"


def _parse_tmux_line(line: str) -> DiscoveredTarget | None:
    line = line.strip()
    if not line:
        return None
    # tmux format expected: session:window.pane
    if ":" not in line or "." not in line:
        return None
    session, tail = line.split(":", 1)
    if session.startswith(EPHEMERAL_VIEW_PREFIX):
        return None
    window_s, pane_s = tail.split(".", 1)
    try:
        window = int(window_s)
        pane = int(pane_s)
    except ValueError:
        return None
    return DiscoveredTarget(
        tmux_session=session,
        tmux_window=window,
        tmux_pane=pane,
        tmux_target=f"{session}:{window}.{pane}",
    )


def discover_tmux_targets() -> list[DiscoveredTarget]:
    proc = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{session_name}:#{window_index}.#{pane_index}"],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return []
    targets: list[DiscoveredTarget] = []
    for line in proc.stdout.splitlines():
        parsed = _parse_tmux_line(line)
        if parsed is not None:
            targets.append(parsed)
    return targets


def tmux_server_running() -> bool:
    """Distinguish "no tmux server" from "server up, zero targets" for the UI."""
    proc = subprocess.run(
        ["tmux", "list-sessions"],
        check=False,
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0
