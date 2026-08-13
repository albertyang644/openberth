from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DiscoveredTarget:
    tmux_session: str
    tmux_window: int
    tmux_pane: int
    tmux_target: str


@dataclass(frozen=True)
class TargetRow:
    id: int
    berth_id: int | None
    display_name: str | None
    tmux_session: str
    tmux_window: int
    tmux_pane: int
    tmux_target: str
    sort_order: int
    hidden: bool
    status: str
    last_seen: datetime | None
    notes: str | None
