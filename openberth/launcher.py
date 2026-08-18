from __future__ import annotations

import shlex
import subprocess

from openberth.config import OpenBerthConfig
from openberth.tmux_actions import format_terminal_command


def can_launch(config: OpenBerthConfig) -> bool:
    return config.viewer.attach_enabled and config.viewer.type in {
        "metadata",
        "external_terminal",
    }


def launch_target(config: OpenBerthConfig, tmux_target: str) -> bool:
    if not can_launch(config):
        return False
    cmd = format_terminal_command(config.terminal.command, tmux_target)
    try:
        # shlex.split raises ValueError on unbalanced quotes, which a tmux
        # session name is allowed to contain.
        subprocess.Popen(shlex.split(cmd))
    except (OSError, ValueError):
        return False
    return True
