from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time

from openberth.config import OpenBerthConfig
from openberth.discovery import EPHEMERAL_VIEW_PREFIX


def format_terminal_command(command: str, tmux_target: str) -> str:
    session = tmux_target.split(":", 1)[0]
    window_target = tmux_target.rsplit(".", 1)[0] if "." in tmux_target else tmux_target
    return command.format(
        target=tmux_target,
        session=session,
        window_target=window_target,
    )


def pop_out_target(config: OpenBerthConfig, tmux_target: str) -> bool:
    cmd = format_terminal_command(config.terminal.command, tmux_target)
    try:
        subprocess.Popen(shlex.split(cmd))
    except OSError:
        return False
    return True


def _tmux_attach_argv(tmux_target: str) -> list[str]:
    session = tmux_target.split(":", 1)[0]
    window_target = tmux_target.rsplit(".", 1)[0] if "." in tmux_target else tmux_target
    return [
        "tmux", "attach", "-t", session,
        ";", "select-window", "-t", window_target,
        ";", "select-pane", "-t", tmux_target,
    ]


def _session_has_attached_client(session: str) -> bool:
    proc = subprocess.run(
        ["tmux", "list-clients", "-t", session], check=False, text=True, capture_output=True
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _tmux_grouped_view_argv(tmux_target: str) -> list[str]:
    """tmux's "current window" is per-session, shared by every attached client --
    there is no per-client window state in vanilla tmux. If this session already
    has a client attached (e.g. another popped-out TV from the same session),
    a plain second attach would yank that client's view the instant we
    select-window. A grouped session shares all windows/panes but gets its own
    independent current-window pointer, which is the only real tmux mechanism
    for this. The view is ephemeral and self-destructs via the client-detached
    hook when its wezterm pane closes, and is filtered out of discovery
    (EPHEMERAL_VIEW_PREFIX) so it never shows up as a phantom TV."""
    session = tmux_target.split(":", 1)[0]
    window_index = tmux_target.rsplit(".", 1)[0].rsplit(":", 1)[1]
    view_name = f"{EPHEMERAL_VIEW_PREFIX}{session}_{os.getpid()}_{time.time_ns()}"
    return [
        "tmux", "new-session", "-t", session, "-s", view_name,
        ";", "set-hook", "-t", view_name, "client-detached", f"kill-session -t {view_name}",
        ";", "select-window", "-t", f"{view_name}:{window_index}",
        ";", "select-pane", "-t", tmux_target,
    ]


def _target_parts(tmux_target: str) -> tuple[str, str, str]:
    session = tmux_target.split(":", 1)[0]
    window_target = tmux_target.rsplit(".", 1)[0] if "." in tmux_target else tmux_target
    pane_index = tmux_target.rsplit(".", 1)[1] if "." in tmux_target else "0"
    return session, window_target, pane_index


def _clipboard_command() -> str:
    """VTE does not honor OSC 52 clipboard writes, so tmux's default
    set-clipboard route lands in a tmux paste buffer and nowhere else. Pipe to
    a real clipboard tool instead."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return "wl-copy"
    if shutil.which("xclip"):
        return "xclip -selection clipboard -i"
    if shutil.which("xsel"):
        return "xsel --clipboard --input"
    return ""


def _ensure_copy_command() -> None:
    """Point argument-less `copy-pipe` at a real clipboard tool.

    tmux's MouseDragEnd1Pane binding runs copy-pipe-and-cancel with no
    argument, which pipes to `copy-command`. That option is documented as
    per-session but tmux (through at least 3.4) stores it in the global
    table, so there is no way to scope it -- set it explicitly, once, and
    only when empty, so a deliberate user setting is never clobbered.
    """
    clipboard = _clipboard_command()
    if not clipboard:
        return
    proc = subprocess.run(
        ["tmux", "show-options", "-gv", "copy-command"],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or proc.stdout.strip():
        return
    subprocess.run(["tmux", "set-option", "-g", "copy-command", clipboard], check=False)


def enable_mouse_selection(session: str) -> None:
    """Hand mouse ownership of the pane to tmux for the session a client is
    about to attach to, so drag-to-edge autoscroll and copy-on-drag-end work
    like a normal window.

    The embedded viewer shows an attached tmux client, which draws on the
    alternate screen -- the VTE widget has no scrollback of its own, so its
    drag-to-edge autoscroll has nothing to move. tmux owns the real buffer,
    and root MouseDrag1Pane already runs "copy-mode -M" (real edge-autoscroll)
    whenever the pane isn't already in a mode.

    Right-click is the one collision: root MouseDown3Pane's default action is
    display-menu, which fires from the same physical click that VTE forwards
    to the app's own paste-on-right-click handler -- pasted text then gets
    read as menu accelerator keys (h/v = split, X = kill-pane, R = respawn),
    which is what broke sessions the first time this was tried. Key tables in
    tmux are server-global, not per-session, so this unbind is global too;
    it's idempotent and safe to repeat on every attach. Alt+right-click
    (M-MouseDown3Pane) is left as a deliberate escape hatch to tmux's menu.
    """
    subprocess.run(["tmux", "set-option", "-t", session, "mouse", "on"], check=False)
    subprocess.run(["tmux", "unbind-key", "-T", "root", "MouseDown3Pane"], check=False)
    _ensure_copy_command()


def _prepare_attach_target(tmux_target: str) -> str:
    session, window_target, pane_index = _target_parts(tmux_target)
    if not _session_has_attached_client(session):
        subprocess.run(["tmux", "select-window", "-t", window_target], check=False)
        subprocess.run(["tmux", "select-pane", "-t", tmux_target], check=False)
        enable_mouse_selection(session)
        return session

    window_index = window_target.rsplit(":", 1)[1]
    view_name = f"{EPHEMERAL_VIEW_PREFIX}{session}_{os.getpid()}_{time.time_ns()}"
    proc = subprocess.run(
        ["tmux", "new-session", "-d", "-t", session, "-s", view_name],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        enable_mouse_selection(session)
        return session
    # Grouped sessions share windows but keep independent options, and the
    # original already has a client attached -- flip mouse mode on the
    # ephemeral view, not underneath a terminal someone is actively using.
    enable_mouse_selection(view_name)
    subprocess.run(
        ["tmux", "set-hook", "-t", view_name, "client-detached", f"kill-session -t {view_name}"],
        check=False,
    )
    subprocess.run(["tmux", "select-window", "-t", f"{view_name}:{window_index}"], check=False)
    subprocess.run(
        ["tmux", "select-pane", "-t", f"{view_name}:{window_index}.{pane_index}"],
        check=False,
    )
    return view_name


def attach_argv_for_target(tmux_target: str) -> list[str]:
    return ["tmux", "attach", "-t", _prepare_attach_target(tmux_target)]


def _wezterm_cli_list() -> list[dict]:
    proc = subprocess.run(
        ["wezterm", "cli", "list", "--format", "json"], check=False, text=True, capture_output=True
    )
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def _window_id_for_pane(pane_id: str) -> str | None:
    for pane in _wezterm_cli_list():
        if str(pane.get("pane_id")) == str(pane_id):
            return str(pane.get("window_id"))
    return None


def pop_out_docked(tmux_target: str, *, berth_id: int | None, store) -> bool:
    """Pop out via `wezterm cli spawn` instead of the ambiguous `wezterm start --`,
    which can land in any already-running wezterm-gui instance. TVs in the same
    berth are docked as tabs in one tracked window; ungrouped TVs each get a
    fresh, deterministic new window instead of guessing."""
    argv = attach_argv_for_target(tmux_target)
    window_id = store.get_berth_window(berth_id) if berth_id is not None else None
    if window_id is not None and not any(
        str(p.get("window_id")) == window_id for p in _wezterm_cli_list()
    ):
        window_id = None  # tracked window closed since last pop-out

    if window_id is not None:
        proc = subprocess.run(
            ["wezterm", "cli", "spawn", "--window-id", window_id, "--", *argv],
            check=False, text=True, capture_output=True,
        )
        if proc.returncode == 0:
            return True
        # tracked window vanished between the check and the spawn; fall through

    proc = subprocess.run(
        ["wezterm", "cli", "spawn", "--new-window", "--", *argv],
        check=False, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        return False
    if berth_id is not None:
        new_window_id = _window_id_for_pane(proc.stdout.strip())
        if new_window_id is not None:
            store.set_berth_window(berth_id, new_window_id)
    return True


def _pane_pid(tmux_target: str) -> str | None:
    proc = subprocess.run(
        ["tmux", "display-message", "-p", "-t", tmux_target, "#{pane_pid}"],
        check=False,
        text=True,
        capture_output=True,
    )
    pid = proc.stdout.strip()
    return pid if proc.returncode == 0 and pid else None


def _pane_unique_id(tmux_target: str) -> str | None:
    proc = subprocess.run(
        ["tmux", "display-message", "-p", "-t", tmux_target, "#{pane_id}"],
        check=False,
        text=True,
        capture_output=True,
    )
    pane_id = proc.stdout.strip()
    return pane_id if proc.returncode == 0 and pane_id else None


def kill_target(tmux_target: str, *, confirmed: bool) -> bool:
    if not confirmed:
        return False
    pid = _pane_pid(tmux_target)
    # tmux's stable "%N" pane id, not the "session:window.pane" string, which
    # tmux can reuse for a *different* pane the instant this window closes.
    pane_id = _pane_unique_id(tmux_target)
    check_target = pane_id or tmux_target
    subprocess.run(["tmux", "kill-pane", "-t", tmux_target], check=False)
    # kill-pane sends SIGHUP; processes that ignore it (nohup, traps, etc.)
    # keep the pane alive, so fall back to SIGKILL on the pane's process.
    if pid is not None and _pane_pid(check_target) is not None:
        subprocess.run(["kill", "-9", pid], check=False)
    return _pane_pid(check_target) is None


def create_target(session_name: str | None = None) -> str | None:
    name = session_name or f"openberth-{int(time.time())}"
    proc = subprocess.run(["tmux", "new-session", "-d", "-s", name], check=False)
    if proc.returncode != 0:
        return None
    target = subprocess.run(
        ["tmux", "list-panes", "-t", name, "-F", "#{session_name}:#{window_index}.#{pane_index}"],
        check=False,
        text=True,
        capture_output=True,
    )
    line = target.stdout.strip().splitlines()[0] if target.stdout.strip() else None
    return line


def set_session_status_style(tmux_target: str, bg: str, fg: str) -> bool:
    session = tmux_target.split(":", 1)[0]
    proc = subprocess.run(
        ["tmux", "set-option", "-t", session, "status-style", f"bg={bg},fg={fg}"],
        check=False,
    )
    return proc.returncode == 0


def scroll_target_history(tmux_target: str, *, up: bool, lines: int = 5) -> bool:
    """Scroll a pane's tmux history without turning the wheel into arrow keys.

    An attached tmux client owns the useful scrollback, rather than the VTE
    widget displaying it. Enter copy mode on upward scroll and enable tmux's
    scroll-exit behavior so scrolling back to the bottom resumes the live pane.
    """
    repeat = str(max(1, int(lines)))
    argv = ["tmux"]
    if up:
        argv.extend(["copy-mode", "-e", "-t", tmux_target, ";"])
    argv.extend(
        [
            "send-keys",
            "-X",
            "-t",
            tmux_target,
            "-N",
            repeat,
            "scroll-up" if up else "scroll-down",
        ]
    )
    proc = subprocess.run(argv, check=False)
    return proc.returncode == 0


def exit_copy_mode(tmux_target: str) -> bool:
    """Release a pane frozen in copy-mode after scrolling up.

    scroll_target_history()'s "-e" exit only fires if the user scrolls all
    the way back to the bottom, which selecting text to copy interrupts
    partway through. Without this, the pane stays paused on the scrolled-back
    snapshot indefinitely after a copy.
    """
    proc = subprocess.run(
        ["tmux", "send-keys", "-X", "-t", tmux_target, "cancel"], check=False
    )
    return proc.returncode == 0


def capture_last_lines(tmux_target: str, lines: int) -> list[str]:
    start = -max(1, lines)
    proc = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", tmux_target, "-S", str(start)],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return []
    captured = [line.rstrip() for line in proc.stdout.splitlines()]
    while captured and not captured[-1]:
        captured.pop()
    return captured[-lines:]
