from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ViewerConfig:
    type: str = "embedded_vte"
    attach_enabled: bool = False


@dataclass(frozen=True)
class DiscoveryConfig:
    poll_seconds: int = 5


@dataclass(frozen=True)
class TerminalConfig:
    command: str = (
        '/usr/bin/wezterm start -- tmux attach -t {session} \\; '
        'select-window -t {window_target} \\; select-pane -t {target}'
    )
    # "berth_dock": wezterm cli spawn, one tracked window per berth (reliable).
    # "legacy_command": use `command` above as-is (for non-wezterm terminals).
    dock_mode: str = "berth_dock"


@dataclass(frozen=True)
class UiConfig:
    theme: str = "dark"
    font_family: str = "Sans"
    font_size: int = 13
    mono_font_family: str = "Monospace"
    mono_font_size: int = 12
    hover_preview_enabled: bool = True
    hover_preview_delay_ms: int = 2000


@dataclass(frozen=True)
class PreviewConfig:
    lines: int = 4
    max_line_chars: int = 160
    refresh_min_interval_ms: int = 1000


@dataclass(frozen=True)
class ColorsConfig:
    berth_default: str = "#3b82f6"
    selection: str = "#1f6feb"
    status_alive: str = "#22c55e"
    status_idle: str = "#eab308"
    status_dead: str = "#ef4444"


@dataclass(frozen=True)
class OpenBerthConfig:
    viewer: ViewerConfig = ViewerConfig()
    discovery: DiscoveryConfig = DiscoveryConfig()
    terminal: TerminalConfig = TerminalConfig()
    ui: UiConfig = UiConfig()
    preview: PreviewConfig = PreviewConfig()
    colors: ColorsConfig = ColorsConfig()


def _viewer_type(value: object) -> str:
    if value in {"metadata", "external_terminal", "embedded_vte"}:
        return str(value)
    return "metadata"


def _ui_theme(value: object) -> str:
    return "light" if value == "light" else "dark"


def _coerce_color(value: object, default: str) -> str:
    v = str(value) if value is not None else default
    if v.startswith("#") and len(v) in {4, 7}:
        return v
    return default


def load_config(path: str | Path | None = None) -> OpenBerthConfig:
    if path is None:
        cfg_path = Path.home() / ".openberth.toml"
    else:
        cfg_path = Path(path)

    if not cfg_path.exists():
        return OpenBerthConfig()

    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    viewer = data.get("viewer", {})
    discovery = data.get("discovery", {})
    terminal = data.get("terminal", {})
    ui = data.get("ui", {})
    preview = data.get("preview", {})
    colors = data.get("colors", {})

    return OpenBerthConfig(
        viewer=ViewerConfig(
            type=_viewer_type(viewer.get("type", ViewerConfig.type)),
            attach_enabled=bool(viewer.get("attach_enabled", False)),
        ),
        discovery=DiscoveryConfig(
            poll_seconds=max(1, int(discovery.get("poll_seconds", 5))),
        ),
        terminal=TerminalConfig(
            command=str(terminal.get("command", TerminalConfig.command)),
            dock_mode=str(terminal.get("dock_mode", TerminalConfig.dock_mode)),
        ),
        ui=UiConfig(
            theme=_ui_theme(ui.get("theme")),
            font_family=str(ui.get("font_family", UiConfig.font_family)),
            font_size=max(10, int(ui.get("font_size", UiConfig.font_size))),
            mono_font_family=str(ui.get("mono_font_family", UiConfig.mono_font_family)),
            mono_font_size=max(10, int(ui.get("mono_font_size", UiConfig.mono_font_size))),
            hover_preview_enabled=bool(ui.get("hover_preview_enabled", UiConfig.hover_preview_enabled)),
            hover_preview_delay_ms=max(100, int(ui.get("hover_preview_delay_ms", UiConfig.hover_preview_delay_ms))),
        ),
        preview=PreviewConfig(
            lines=max(1, int(preview.get("lines", PreviewConfig.lines))),
            max_line_chars=max(40, int(preview.get("max_line_chars", PreviewConfig.max_line_chars))),
            refresh_min_interval_ms=max(
                0, int(preview.get("refresh_min_interval_ms", PreviewConfig.refresh_min_interval_ms))
            ),
        ),
        colors=ColorsConfig(
            berth_default=_coerce_color(colors.get("berth_default"), ColorsConfig.berth_default),
            selection=_coerce_color(colors.get("selection"), ColorsConfig.selection),
            status_alive=_coerce_color(colors.get("status_alive"), ColorsConfig.status_alive),
            status_idle=_coerce_color(colors.get("status_idle"), ColorsConfig.status_idle),
            status_dead=_coerce_color(colors.get("status_dead"), ColorsConfig.status_dead),
        ),
    )
