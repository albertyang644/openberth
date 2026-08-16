from __future__ import annotations

import argparse
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

# VTE's GTK4 typelib is an apt package and may live outside a conda env's
# search paths; extend them so `gi.require_version("Vte", "3.91")` can find it.
for _extra in ("/usr/lib/x86_64-linux-gnu/girepository-1.0",):
    if os.path.isdir(_extra) and _extra not in os.environ.get("GI_TYPELIB_PATH", ""):
        os.environ["GI_TYPELIB_PATH"] = _extra + os.pathsep + os.environ.get("GI_TYPELIB_PATH", "")
for _extra in ("/usr/lib/x86_64-linux-gnu",):
    if os.path.isdir(_extra) and _extra not in os.environ.get("LD_LIBRARY_PATH", ""):
        os.environ["LD_LIBRARY_PATH"] = _extra + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")

import gi

from openberth.config import OpenBerthConfig, load_config
from openberth.discovery import discover_tmux_targets, tmux_server_running
from openberth.grouping import (
    link_targets_to_new_berth,
    move_targets_to_berth,
    reorder_within_berth,
    unlink_targets,
)
from openberth.launcher import can_launch, launch_target
from openberth.models import TargetRow
from openberth.selection import SelectionModel
from openberth.store import Store
from openberth.tmux_actions import (
    attach_argv_for_target,
    capture_last_lines,
    create_target,
    exit_copy_mode,
    kill_target,
    pop_out_docked,
    pop_out_target,
    set_session_status_style,
)

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte  # noqa: E402
except (ValueError, ImportError):
    Vte = None

PALETTE = ["#64748b", "#ef4444", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6"]
UNGROUPED_COLOR = "#94a3b8"
# Embedded terminal colors. VTE's built-in ANSI palette has a near-unreadable
# dark blue; this modern palette keeps every color legible on a dark background.
TERM_FG = "#e5e7eb"
TERM_BG = "#0a0d12"
TERM_ANSI = [
    "#14161c", "#ef4444", "#22c55e", "#eab308",  # black red green yellow
    "#60a5fa", "#c084fc", "#22d3ee", "#d1d5db",  # blue magenta cyan white
    "#6b7280", "#f87171", "#4ade80", "#facc15",  # bright variants
    "#93c5fd", "#d8b4fe", "#67e8f9", "#f9fafb",
]
DEFAULT_UNGROUPED_NAME = "Ungrouped"
PREVIEW_CAPTURE_LINES = 40
APPLICATION_ID = "com.openberth.app"


def _rgba(color: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(color)
    return rgba


def _contrast_fg(color: str) -> str:
    r, g, b = _hex_rgb(color)
    return "#0e1116" if (0.299 * r + 0.587 * g + 0.114 * b) > 0.6 else "#f8fafc"


def _hex_rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    try:
        return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.5, 0.5, 0.5)


def _nonspace_runs(line: str) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, ch in enumerate(line):
        if ch.isspace():
            if start is not None:
                runs.append((start, i - start))
                start = None
        elif start is None:
            start = i
    if start is not None:
        runs.append((start, len(line) - start))
    return runs


class Minimap(Gtk.DrawingArea):
    """Compressed activity map of a tmux pane, minimap-style (no screenshot, no terminal)."""

    ROWS = 16
    COLS = 72

    def __init__(self, accent: str):
        super().__init__()
        self.set_content_width(74)
        self.set_content_height(74)
        self.accent = accent
        self.status = "alive"
        self.lines: list[str] = []
        self.set_draw_func(self._draw)

    def update(self, status: str, text: str | None) -> None:
        self.status = status
        self.lines = text.splitlines()[-self.ROWS :] if text else []
        self.queue_draw()

    def _draw(self, _area, cr, w, h) -> None:
        pad = 7.0
        inner_w = w - 2 * pad
        inner_h = h - 2 * pad
        row_h = inner_h / self.ROWS
        bar_h = max(1.0, row_h * 0.5)
        alive = self.status == "alive"
        cr.set_source_rgb(*_hex_rgb(self.accent if alive else "#4b5563"))
        if alive and not self.lines:
            for i in (5, 8, 11):
                cr.rectangle(pad, pad + i * row_h, inner_w * 0.4, bar_h)
            cr.fill()
        for i, line in enumerate(self.lines):
            y = pad + i * row_h + row_h * 0.25
            for run_start, run_len in _nonspace_runs(line[: self.COLS]):
                x = pad + (run_start / self.COLS) * inner_w
                bw = max(1.5, (run_len / self.COLS) * inner_w)
                cr.rectangle(x, y, bw, bar_h)
            cr.fill()
        if not alive:
            cr.set_source_rgb(*_hex_rgb("#ef4444"))
            cr.set_line_width(2.0)
            cr.move_to(pad, pad)
            cr.line_to(w - pad, h - pad)
            cr.move_to(w - pad, pad)
            cr.line_to(pad, h - pad)
            cr.stroke()


class OpenBerthWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, store: Store, config: OpenBerthConfig):
        super().__init__(application=app, title="OpenBerth")
        self.store = store
        self.config = config
        self.selection = SelectionModel()
        self.selected_berth_id: int | None = None
        self.collapsed: set[int] = set()
        self.query = ""
        self.row_order: list[int] = []
        self.minimaps: dict[int, Minimap] = {}
        self.tile_rows: dict[int, Gtk.Box] = {}
        self.berth_labels: dict[int | None, Gtk.Label] = {}
        self.berth_entries: dict[int | None, Gtk.Entry] = {}
        self.hover_timers: dict[int, int] = {}
        self.session_status_colors: dict[str, str] = {}
        self.mono_font_size = self.config.ui.mono_font_size
        self.ungrouped_name = DEFAULT_UNGROUPED_NAME
        self._snapshot: object = None
        self.set_default_size(1320, 880)

        self.paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.paned.set_wide_handle(True)
        self.paned.set_position(360)
        self.set_child(self.paned)

        # Actions must exist before panels are built: _menu_popover resolves
        # win.* actions at construction time and disables items it can't find.
        self._register_actions()
        self._build_left_panel()
        self._build_right_panel()
        self._install_shortcuts()
        self._load_css()
        self._load_ui_state()

        self._refresh_previews()
        self.refresh(discover=True)
        if not self.selection.selected and self.row_order:
            self.selection.single_click(self.row_order[0], 0)
            self._apply_selection()

        GLib.timeout_add_seconds(self.config.discovery.poll_seconds, self._on_poll)
        self.connect("close-request", self._on_close_request)

    # ---------- layout ----------

    def _build_left_panel(self) -> None:
        self.left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.left.set_css_classes(["harbor"])
        self.left.set_size_request(250, -1)
        self.paned.set_start_child(self.left)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_css_classes(["harbor-top"])
        title = Gtk.Label(label="OpenBerth", xalign=0)
        title.set_css_classes(["hdr"])
        top.append(title)
        link = Gtk.Button.new_from_icon_name("insert-link-symbolic")
        link.set_css_classes(["utility-button"])
        link.set_tooltip_text("Chain-Link Selected TVs Into a Berth")
        link.connect("clicked", lambda *_: self._chain_link())
        top.append(link)
        unlink = Gtk.Button.new_from_icon_name("edit-cut-symbolic")
        unlink.set_css_classes(["utility-button"])
        unlink.set_tooltip_text("Unlink Selected TVs")
        unlink.connect("clicked", lambda *_: self._unlink_selected())
        top.append(unlink)
        top.append(Gtk.Box(hexpand=True))
        btn_restore = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        btn_restore.set_css_classes(["icon-button"])
        btn_restore.set_tooltip_text("Restore Closed TV (Ctrl+Shift+T)")
        btn_restore.connect("clicked", lambda *_: self._restore_tv())
        top.append(btn_restore)
        btn_new = Gtk.Button.new_from_icon_name("folder-new-symbolic")
        btn_new.set_css_classes(["icon-button"])
        btn_new.set_tooltip_text("New Berth + TV")
        btn_new.connect("clicked", lambda *_: self._prompt_create_berth())
        top.append(btn_new)
        settings = Gtk.MenuButton()
        settings.set_icon_name("open-menu-symbolic")
        settings.set_css_classes(["icon-button"])
        settings.set_tooltip_text("Settings")
        menu = Gio.Menu()
        menu.append("Larger Terminal Font", "win.font-increase")
        menu.append("Smaller Terminal Font", "win.font-decrease")
        menu.append("Reset Terminal Font", "win.font-reset")
        menu.append("Focus Terminal", "win.terminal-focus")
        settings.set_popover(_menu_popover(menu, self))
        top.append(settings)
        self.left.append(top)

        self.health_banner = Gtk.Label(label="tmux server not running", xalign=0)
        self.health_banner.set_css_classes(["health-banner"])
        self.health_banner.set_visible(False)
        self.left.append(self.health_banner)

        self.search = Gtk.SearchEntry()
        self.search.set_css_classes(["search-box"])
        self.search.set_placeholder_text("Search (Ctrl+P)")
        self.search.connect("search-changed", self._on_search_changed)
        self.left.append(self.search)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_css_classes(["harbor-scroll"])
        self.harbor_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.harbor_body.set_margin_start(8)
        self.harbor_body.set_margin_end(8)
        self.harbor_body.set_margin_bottom(8)
        scrolled.set_child(self.harbor_body)
        self.left.append(scrolled)

        palette = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        palette.set_css_classes(["palette"])
        for color in PALETTE:
            b = Gtk.Button()
            b.set_css_classes(["swatch-btn"])
            b.set_tooltip_text("Color Selected Berth")
            sw = Gtk.Box()
            sw.set_size_request(20, 20)
            sw.set_css_classes(["swatch"])
            _set_widget_bg(sw, color)
            b.set_child(sw)
            b.connect("clicked", self._on_palette_pick, color)
            palette.append(b)
        custom = Gtk.Button.new_from_icon_name("color-select-symbolic")
        custom.set_tooltip_text("Custom Color")
        custom.set_css_classes(["swatch-btn"])
        custom.connect("clicked", lambda *_: self._prompt_custom_color())
        palette.append(custom)
        self.left.append(palette)

    def _build_right_panel(self) -> None:
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_css_classes(["meta"])
        right.set_margin_top(18)
        right.set_margin_start(18)
        right.set_margin_end(18)
        right.set_margin_bottom(18)
        self.paned.set_end_child(right)

        self.active_chip = Gtk.Frame()
        self.active_chip.set_css_classes(["active-chip"])
        chip_box = Gtk.Box(halign=Gtk.Align.CENTER, spacing=8)
        chip_box.set_size_request(0, 48)
        self.active_chip_label = Gtk.Label(label="No Active TV")
        self.active_chip_label.set_css_classes(["active-chip-label"])
        self.active_chip_label.set_valign(Gtk.Align.CENTER)
        chip_box.append(self.active_chip_label)
        self.inherit_btn = Gtk.Button.new_from_icon_name("folder-download-symbolic")
        self.inherit_btn.set_css_classes(["chip-action"])
        self.inherit_btn.set_tooltip_text("Inherit Category Name")
        self.inherit_btn.set_valign(Gtk.Align.CENTER)
        self.inherit_btn.set_sensitive(False)
        self.inherit_btn.connect("clicked", lambda *_: self._inherit_berth_name())
        chip_box.append(self.inherit_btn)
        self.active_chip.set_child(chip_box)
        self.active_chip.set_tooltip_text("Double-click to rename active TV")
        active_click = Gtk.GestureClick()
        active_click.set_button(0)
        active_click.connect("pressed", self._on_active_chip_pressed)
        self.active_chip.add_controller(active_click)
        right.append(self.active_chip)

        self.meta_line = Gtk.Label(label="", xalign=0)
        self.meta_line.set_css_classes(["meta-line"])
        right.append(self.meta_line)

        frame = Gtk.Frame(hexpand=True, vexpand=True)
        frame.set_css_classes(["term-frame"])
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.preview_label = Gtk.Label(label="", xalign=0, yalign=0)
        self.preview_label.set_selectable(True)
        self.preview_label.set_css_classes(["term-text"])
        scroll.set_child(self.preview_label)
        frame.set_child(scroll)
        right.append(frame)

        self.vte_terminal = None
        self.vte_target: str | None = None
        self.vte_child_pid: int | None = None
        if Vte is not None and self.config.viewer.type == "embedded_vte":
            frame.set_child(None)
            self.vte_terminal = Vte.Terminal()
            self.vte_terminal.set_size_request(-1, -1)
            self.vte_terminal.set_focusable(True)
            self.vte_terminal.set_input_enabled(True)
            # tmux owns the mouse in an attached TV (enable_mouse_selection),
            # including the wheel, so this fallback never applies. Kept as a
            # guard: if enabling mouse mode ever fails, VTE would otherwise
            # map wheel events on the alternate screen to Up/Down keys and
            # leak them into the program running in the pane.
            self.vte_terminal.set_enable_fallback_scrolling(False)
            self.vte_terminal.set_colors(
                _rgba(TERM_FG), _rgba(TERM_BG), [_rgba(c) for c in TERM_ANSI]
            )
            self.vte_terminal.connect("child-exited", self._on_vte_child_exited)
            self.vte_terminal.connect("selection-changed", self._on_vte_selection_changed)
            paste_click = Gtk.GestureClick()
            paste_click.set_button(3)
            paste_click.connect("pressed", self._on_vte_right_click)
            self.vte_terminal.add_controller(paste_click)
            font_desc = Pango.FontDescription.from_string(
                f"{self.config.ui.mono_font_family} {self.mono_font_size}"
            )
            self.vte_terminal.set_font(font_desc)
            frame.set_child(self.vte_terminal)

        if self.config.viewer.attach_enabled:
            attach = Gtk.Button(label="Attach In Terminal")
            attach.set_css_classes(["primary-button"])
            attach.set_halign(Gtk.Align.END)
            attach.connect("clicked", self._on_attach_clicked)
            right.append(attach)

    # ---------- actions / shortcuts ----------

    def _register_actions(self) -> None:
        handlers = {
            "tv-open": self._open_tv,
            "tv-pop": self._pop_tv,
            "tv-rename": self._prompt_rename_target,
            "tv-move": self._prompt_move_target,
            "tv-copy-target": self._copy_tmux_target,
            "tv-copy-name": self._copy_tv_name,
            "tv-close": self._close_tv,
            "tv-kill": self._confirm_kill_tv,
            "berth-new-tv": self._new_tv_in_berth,
            "berth-select-tvs": self._select_berth_tvs,
            "berth-unlink-tvs": self._unlink_berth_targets,
            "berth-rename": self._prompt_rename_berth,
            "berth-color": self._prompt_berth_color,
            "berth-toggle": self._toggle_berth_collapse,
            "berth-move-up": lambda bid: self._move_berth(bid, -1),
            "berth-move-down": lambda bid: self._move_berth(bid, 1),
            "berth-delete": self._delete_berth,
        }
        for name, callback in handlers.items():
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("i"))
            action.connect("activate", self._dispatch_action, callback)
            self.add_action(action)
        simple_handlers = {
            "font-increase": lambda: self._change_mono_font_size(1),
            "font-decrease": lambda: self._change_mono_font_size(-1),
            "font-reset": self._reset_mono_font_size,
            "terminal-focus": self._focus_terminal,
            "ungrouped-rename": self._prompt_rename_ungrouped,
            "ungrouped-select-tvs": self._select_ungrouped_tvs,
        }
        for name, callback in simple_handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, fn=callback: fn())
            self.add_action(action)

    @staticmethod
    def _dispatch_action(_action, param, callback) -> None:
        callback(int(param.get_int32()))

    def _install_shortcuts(self) -> None:
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and shift and keyval in (Gdk.KEY_T, Gdk.KEY_t):
            self._restore_tv()
            return True
        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._change_mono_font_size(1)
            return True
        if ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_underscore, Gdk.KEY_KP_Subtract):
            self._change_mono_font_size(-1)
            return True
        if ctrl and keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._reset_mono_font_size()
            return True
        if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self.search.grab_focus()
            return True
        focus = self.get_focus()
        if isinstance(focus, Gtk.Text) or (
            Vte is not None and isinstance(focus, Vte.Terminal)
        ):
            return False
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            active = self._active_target()
            if active is not None:
                self._open_tv(active.id)
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and self.row_order:
            self._move_selection(-1 if keyval == Gdk.KEY_Up else 1)
            return True
        if keyval == Gdk.KEY_Delete:
            active = self._active_target()
            if active is not None:
                self._confirm_kill_tv(active.id) if shift else self._close_tv(active.id)
            return True
        return False

    def _move_selection(self, delta: int) -> None:
        active = self._active_target()
        index = self.row_order.index(active.id) if active is not None and active.id in self.row_order else 0
        new_index = max(0, min(len(self.row_order) - 1, index + delta))
        new_id = self.row_order[new_index]
        self.selection.single_click(new_id, new_index)
        self._apply_selection()
        self._save_ui_state()

    # ---------- data access ----------

    def _visible_targets(self) -> list[TargetRow]:
        targets = self.store.list_targets(include_hidden=False)
        q = self.query.strip().lower()
        if not q:
            return targets
        return [
            t
            for t in targets
            if q in (t.display_name or "").lower()
            or q in t.tmux_target.lower()
            or q in self._berth_name(t.berth_id).lower()
        ]

    def _target_by_id(self, target_id: int) -> TargetRow | None:
        return next(
            (t for t in self.store.list_targets(include_hidden=False) if t.id == target_id), None
        )

    def _berth_name(self, berth_id: int | None) -> str:
        if berth_id is None:
            return self.ungrouped_name
        row = self.store.get_berth(berth_id)
        return DEFAULT_UNGROUPED_NAME if row is None else str(row["name"])

    def _berth_color(self, berth_id: int | None) -> str:
        if berth_id is None:
            return UNGROUPED_COLOR
        row = self.store.get_berth(berth_id)
        if row is None or not row["color"]:
            return self.config.colors.berth_default
        return str(row["color"])

    def _target_title(self, target: TargetRow) -> str:
        name = (target.display_name or "").strip()
        if name:
            return name
        berth_name = self._berth_name(target.berth_id)
        if target.berth_id is not None and berth_name != "Ungrouped":
            return berth_name
        return target.tmux_target

    def _status_color(self, status: str) -> str:
        if status == "alive":
            return self.config.colors.status_alive
        if status == "idle":
            return self.config.colors.status_idle
        return self.config.colors.status_dead

    def _active_target(self) -> TargetRow | None:
        if not self.selection.selected:
            return None
        first = next((tid for tid in self.row_order if tid in self.selection.selected), None)
        if first is None:
            first = next(iter(self.selection.selected))
        return self._target_by_id(first)

    def _structure_snapshot(self) -> object:
        targets = tuple(
            (t.id, t.berth_id, t.display_name, t.status) for t in self._visible_targets()
        )
        berths = tuple(
            (int(r["id"]), str(r["name"]), str(r["color"] or "")) for r in self.store.list_berths()
        )
        return (targets, berths, frozenset(self.collapsed))

    # ---------- harbor rendering ----------

    def refresh(self, discover: bool = False) -> None:
        if discover:
            self.store.upsert_discovered_targets(discover_tmux_targets())
            self.health_banner.set_visible(not tmux_server_running())
        for child in list(_iter_children(self.harbor_body)):
            self.harbor_body.remove(child)
        self.minimaps.clear()
        self.tile_rows.clear()
        self.berth_labels.clear()
        self.berth_entries.clear()

        targets = self._visible_targets()
        self.row_order = [t.id for t in targets]

        berths = self.store.list_berths()
        grouped: dict[int | None, list[TargetRow]] = {None: []}
        for row in berths:
            grouped[int(row["id"])] = []
        for t in targets:
            grouped.setdefault(t.berth_id, []).append(t)

        if grouped[None]:
            self._append_berth_section(None, self._berth_name(None), UNGROUPED_COLOR, grouped[None])
        for row in berths:
            bid = int(row["id"])
            color = str(row["color"] or self.config.colors.berth_default)
            self._append_berth_section(bid, str(row["name"]), color, grouped[bid])

        self._sync_session_colors(targets)
        self._snapshot = self._structure_snapshot()
        self._render_meta(self._active_target())

    def _sync_session_colors(self, targets: list[TargetRow]) -> None:
        """Keep each tmux session's status bar tinted with its berth color, so
        the bar inside a TV (embedded or popped out) matches the Harbor."""
        for t in targets:
            if t.status != "alive":
                continue
            session = t.tmux_target.split(":", 1)[0]
            color = self._berth_color(t.berth_id)
            if self.session_status_colors.get(session) == color:
                continue
            if set_session_status_style(t.tmux_target, color, _contrast_fg(color)):
                self.session_status_colors[session] = color

    def _append_berth_section(
        self, berth_id: int | None, name: str, color: str, targets: list[TargetRow]
    ) -> None:
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        section.set_css_classes(["berth-section"])

        caret = "▸ " if berth_id in self.collapsed else ""
        name_lbl = Gtk.Label(label=caret + name, xalign=0)
        classes = ["berth-name"]
        if berth_id is not None and berth_id == self.selected_berth_id:
            classes.append("berth-selected")
        name_lbl.set_css_classes(classes)
        _set_widget_fg(name_lbl, color)
        self.berth_labels[berth_id] = name_lbl

        alive = sum(1 for t in targets if t.status == "alive")
        count_lbl = Gtk.Label(label=f"{alive}/{len(targets)}")
        count_lbl.set_css_classes(["berth-count"])
        count_lbl.set_tooltip_text("Alive TVs / total TVs")

        stack = Gtk.Stack()
        stack.add_named(name_lbl, "label")

        entry = Gtk.Entry()
        entry.set_text(name)
        entry.set_css_classes(["berth-name-edit"])
        entry.connect("activate", self._on_berth_rename_commit, berth_id, stack)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", self._on_berth_rename_commit, berth_id, stack)
        entry.add_controller(focus)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_berth_rename_key, stack)
        entry.add_controller(key)
        stack.add_named(entry, "edit")
        self.berth_entries[berth_id] = entry

        stack.set_visible_child_name("label")
        stack.set_hexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_css_classes(["berth-header"])
        if berth_id is not None:
            for icon, tooltip, delta in [
                ("pan-up-symbolic", "Move Berth Up", -1),
                ("pan-down-symbolic", "Move Berth Down", 1),
            ]:
                move = Gtk.Button.new_from_icon_name(icon)
                move.set_css_classes(["berth-move-btn"])
                move.set_tooltip_text(tooltip)
                move.connect(
                    "clicked", lambda _b, bid=berth_id, d=delta: self._move_berth(bid, d)
                )
                header.append(move)
        header.append(stack)
        header.append(count_lbl)

        select = Gtk.GestureClick.new()
        select.set_button(1)
        select.connect("pressed", self._on_berth_name_pressed, berth_id, stack)
        name_lbl.add_controller(select)
        menu_click = Gtk.GestureClick.new()
        menu_click.set_button(3)
        if berth_id is None:
            menu_click.connect("pressed", self._on_ungrouped_right_click)
        else:
            menu_click.connect("pressed", self._on_berth_right_click, berth_id)
        name_lbl.add_controller(menu_click)

        if berth_id is not None:
            add_tv = Gtk.Button.new_from_icon_name("list-add-symbolic")
            add_tv.set_css_classes(["berth-add-tv"])
            add_tv.set_tooltip_text("Add TV Here")
            add_tv.connect("clicked", lambda *_a, bid=berth_id: self._new_tv_in_berth(bid))
            header.append(add_tv)
        section.append(header)

        if berth_id not in self.collapsed:
            tiles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            tiles.set_css_classes(["berth-tiles"])
            for t in targets:
                tiles.append(self._tile_widget(t, color))
            section.append(tiles)

        drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        drop.connect("drop", self._on_drop_to_berth, berth_id)
        section.add_controller(drop)

        self.harbor_body.append(section)

    def _tile_widget(self, t: TargetRow, berth_color: str) -> Gtk.Widget:
        selected = t.id in self.selection.selected
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_css_classes(["tv-tile", "selected"] if selected else ["tv-tile"])
        row.set_halign(Gtk.Align.FILL)
        row.set_hexpand(True)

        hit = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hit.set_css_classes(["tile-hit"])
        hit.set_hexpand(True)
        monitor = Gtk.Frame()
        monitor.set_css_classes(["monitor"])
        _set_widget_border(monitor, berth_color)
        minimap = Minimap(berth_color)
        text, _updated = self.store.get_preview(t.id)
        minimap.update(t.status, text)
        monitor.set_child(minimap)
        hit.append(monitor)

        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        detail.set_css_classes(["tile-detail"])
        detail.set_hexpand(True)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_dot = Gtk.Box()
        status_dot.set_size_request(8, 8)
        status_dot.set_css_classes(["status-dot"])
        status_accent = berth_color if t.status == "alive" else self._status_color(t.status)
        _set_widget_bg(status_dot, status_accent)
        title_row.append(status_dot)
        name_lbl = Gtk.Label(label=self._target_title(t))
        name_lbl.set_css_classes(["tv-name"])
        name_lbl.set_max_width_chars(18)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_lbl.set_xalign(0)
        title_row.append(name_lbl)
        detail.append(title_row)

        target_lbl = Gtk.Label(label=t.tmux_target, xalign=0)
        target_lbl.set_css_classes(["tv-target"])
        target_lbl.set_max_width_chars(22)
        target_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        detail.append(target_lbl)

        status_lbl = Gtk.Label(label=t.status.upper(), xalign=0)
        status_lbl.set_css_classes(["tv-status"])
        _set_widget_fg(status_lbl, status_accent)
        detail.append(status_lbl)
        hit.append(detail)
        row.append(hit)

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for icon_name, tooltip, css, handler in [
            ("window-new-symbolic", "Pop Out", "open-action", self._pop_tv),
            ("window-close-symbolic", "Close TV (keeps tmux running)", "close-action", self._close_tv),
            ("process-stop-symbolic", "Kill tmux Target", "kill-action", self._confirm_kill_tv),
        ]:
            b = Gtk.Button.new_from_icon_name(icon_name)
            b.set_css_classes(["tile-action", css])
            b.set_tooltip_text(tooltip)
            b.connect("clicked", lambda _b, tid=t.id, fn=handler: fn(tid))
            actions.append(b)
        row.append(actions)

        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("pressed", self._on_tile_pressed, t.id)
        hit.add_controller(click)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect("pressed", self._on_tile_right_click, t.id)
        row.add_controller(right_click)

        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.MOVE)
        drag.connect(
            "prepare", lambda *_a, tid=t.id: Gdk.ContentProvider.new_for_value(str(tid))
        )
        hit.add_controller(drag)

        tile_drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        tile_drop.connect("drop", self._on_drop_on_tile, t.id, t.berth_id)
        row.add_controller(tile_drop)

        if self.config.ui.hover_preview_enabled:
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", self._on_tile_hover_enter, t.id)
            motion.connect("leave", self._on_tile_hover_leave, t.id)
            hit.add_controller(motion)

        self.minimaps[t.id] = minimap
        self.tile_rows[t.id] = row
        return row

    def _apply_selection(self) -> None:
        for tid, row in self.tile_rows.items():
            if tid in self.selection.selected:
                row.add_css_class("selected")
            else:
                row.remove_css_class("selected")
        self._render_meta(self._active_target())

    # ---------- selection ----------

    def _on_tile_pressed(self, gesture, n_press, _x, _y, target_id: int):
        state = gesture.get_current_event_state()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if n_press == 2 and not (ctrl or shift):
            self._open_tv(target_id)
            return
        if n_press != 1 or target_id not in self.row_order:
            return
        index = self.row_order.index(target_id)
        if shift:
            self.selection.shift_click(self.row_order, index)
        elif ctrl:
            self.selection.ctrl_click(target_id, index)
        else:
            self.selection.single_click(target_id, index)
        self._apply_selection()
        self._save_ui_state()

    def _on_berth_name_pressed(
        self, _gesture, n_press, _x, _y, berth_id: int | None, stack: Gtk.Stack
    ) -> None:
        if n_press == 2:
            entry = self.berth_entries[berth_id]
            entry.set_text(self._berth_name(berth_id))
            stack.set_visible_child_name("edit")
            entry.grab_focus()
            entry.select_region(0, -1)
        elif n_press == 1 and berth_id is not None:
            self._select_berth(berth_id)

    def _on_berth_rename_commit(self, widget, *args) -> None:
        berth_id = args[-2]
        stack = args[-1]
        entry = self.berth_entries.get(berth_id)
        name = entry.get_text().strip() if entry else ""
        if stack.get_visible_child_name() != "edit":
            return
        if name and name != self._berth_name(berth_id):
            self._rename_berth(berth_id, name)
        else:
            stack.set_visible_child_name("label")

    def _on_berth_rename_key(self, _ctrl, keyval, _keycode, _state, stack: Gtk.Stack) -> bool:
        if keyval == Gdk.KEY_Escape:
            stack.set_visible_child_name("label")
            return True
        return False

    def _on_active_chip_pressed(self, gesture, n_press, _x, _y) -> None:
        target = self._active_target()
        if target is None:
            return
        button = gesture.get_current_button()
        if button == 3:
            menu = Gio.Menu()
            menu.append("Rename TV", f"win.tv-rename({target.id})")
            if target.berth_id is not None:
                menu.append("Rename Berth", f"win.berth-rename({target.berth_id})")
            menu.append("Copy tmux Target", f"win.tv-copy-target({target.id})")
            self._popup_menu(menu, self.active_chip)
        elif button == 1 and n_press == 2:
            self._prompt_rename_target(target.id)

    def _select_berth(self, berth_id: int) -> None:
        prev = self.berth_labels.get(self.selected_berth_id)
        if prev is not None:
            prev.remove_css_class("berth-selected")
        self.selected_berth_id = berth_id
        current = self.berth_labels.get(berth_id)
        if current is not None:
            current.add_css_class("berth-selected")
        self._save_ui_state()

    # ---------- context menus ----------

    def _popup_menu(self, menu: Gio.Menu, parent: Gtk.Widget) -> None:
        pop = _menu_popover(menu, self)
        pop.set_parent(parent)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _on_tile_right_click(self, _gesture, _n, _x, _y, target_id: int):
        menu = Gio.Menu()
        primary = Gio.Menu()
        for label, action in [
            ("Open", "tv-open"),
            ("Pop Out", "tv-pop"),
            ("Rename", "tv-rename"),
            ("Move To Berth", "tv-move"),
        ]:
            primary.append(label, f"win.{action}({target_id})")
        menu.append_section(None, primary)

        clipboard = Gio.Menu()
        for label, action in [
            ("Copy tmux Target", "tv-copy-target"),
            ("Copy Display Name", "tv-copy-name"),
        ]:
            clipboard.append(label, f"win.{action}({target_id})")
        menu.append_section(None, clipboard)

        danger = Gio.Menu()
        for label, action in [
            ("Close TV", "tv-close"),
            ("Kill Target", "tv-kill"),
        ]:
            danger.append(label, f"win.{action}({target_id})")
        menu.append_section(None, danger)
        self._popup_menu(menu, self.tile_rows[target_id])

    def _on_ungrouped_right_click(self, _gesture, _n, _x, _y) -> None:
        menu = Gio.Menu()
        menu.append("Rename", "win.ungrouped-rename")
        menu.append("Select TVs", "win.ungrouped-select-tvs")
        self._popup_menu(menu, self.berth_labels[None])

    def _on_berth_right_click(self, _gesture, _n, _x, _y, berth_id: int):
        menu = Gio.Menu()
        primary = Gio.Menu()
        primary.append("Add TV Here", f"win.berth-new-tv({berth_id})")
        primary.append("Select TVs", f"win.berth-select-tvs({berth_id})")
        menu.append_section(None, primary)

        organize = Gio.Menu()
        organize.append("Rename", f"win.berth-rename({berth_id})")
        organize.append("Change Color", f"win.berth-color({berth_id})")
        organize.append("Move Up", f"win.berth-move-up({berth_id})")
        organize.append("Move Down", f"win.berth-move-down({berth_id})")
        toggle = "Expand" if berth_id in self.collapsed else "Collapse"
        organize.append(toggle, f"win.berth-toggle({berth_id})")
        menu.append_section(None, organize)

        danger = Gio.Menu()
        danger.append("Unlink All TVs", f"win.berth-unlink-tvs({berth_id})")
        danger.append("Delete Berth", f"win.berth-delete({berth_id})")
        menu.append_section(None, danger)
        self._popup_menu(menu, self.berth_labels[berth_id])

    # ---------- TV actions ----------

    def _open_tv(self, target_id: int) -> None:
        if can_launch(self.config):
            t = self._target_by_id(target_id)
            if t is not None and not launch_target(self.config, t.tmux_target):
                self._error_dialog("Failed to launch terminal. Check [terminal] command in config.")
        else:
            self._pop_tv(target_id)

    def _pop_tv(self, target_id: int) -> None:
        t = self._target_by_id(target_id)
        if t is None:
            return
        if self.config.terminal.dock_mode == "berth_dock":
            ok = pop_out_docked(t.tmux_target, berth_id=t.berth_id, store=self.store)
        else:
            ok = pop_out_target(self.config, t.tmux_target)
        if not ok:
            self._error_dialog("Failed to launch terminal. Check [terminal] command in config.")

    def _copy_text(self, text: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)

    def _copy_tmux_target(self, target_id: int) -> None:
        t = self._target_by_id(target_id)
        if t is not None:
            self._copy_text(t.tmux_target)

    def _copy_tv_name(self, target_id: int) -> None:
        t = self._target_by_id(target_id)
        if t is not None:
            self._copy_text(self._target_title(t))

    def _close_tv(self, target_id: int) -> None:
        index = self.row_order.index(target_id) if target_id in self.row_order else None
        self.store.close_tv(target_id)
        self.selection.selected.discard(target_id)
        self.refresh()
        # Keep keyboard-only flow chainable: closing the active TV should land
        # on a neighbor, like a browser closing a tab, instead of losing focus.
        if not self.selection.selected and self.row_order:
            new_index = min(index, len(self.row_order) - 1) if index is not None else 0
            new_id = self.row_order[new_index]
            self.selection.single_click(new_id, new_index)
            self._apply_selection()
        self._save_ui_state()

    def _restore_tv(self) -> None:
        restored = self.store.restore_last_closed_tv()
        self.refresh()
        if restored is not None and restored in self.row_order:
            self.selection.single_click(restored, self.row_order.index(restored))
            self._apply_selection()
            self._save_ui_state()

    def _new_tv(self) -> None:
        if create_target() is not None:
            self.refresh(discover=True)

    def _new_tv_in_berth(self, berth_id: int) -> None:
        self._create_tv_in_berth(berth_id, display_name=self._berth_name(berth_id))

    def _create_tv_in_berth(self, berth_id: int, display_name: str | None = None) -> int | None:
        target = create_target()
        if target is None:
            self._error_dialog("Failed to create tmux session.")
            return None
        self.store.upsert_discovered_targets(discover_tmux_targets())
        row = next((t for t in self.store.list_targets() if t.tmux_target == target), None)
        if row is not None:
            if display_name:
                self.store.rename_target(row.id, display_name)
            move_targets_to_berth(self.store, berth_id, [row.id])
        self.selected_berth_id = berth_id
        self.collapsed.discard(berth_id)
        self.refresh()
        if row is not None:
            self._select_target(row.id)
            return row.id
        return None

    def _select_target(self, target_id: int) -> None:
        if target_id not in self.row_order:
            return
        target = self._target_by_id(target_id)
        if target is not None:
            self.selected_berth_id = target.berth_id
        self.selection.single_click(target_id, self.row_order.index(target_id))
        self._apply_selection()
        self._save_ui_state()

    def _confirm_kill_tv(self, target_id: int) -> None:
        t = self._target_by_id(target_id)
        if t is None:
            return
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            message_type=Gtk.MessageType.WARNING,
            text=f"Kill tmux target {t.tmux_target}?",
            secondary_text="This kills the running process. It cannot be undone.",
        )
        dlg.connect("response", self._on_kill_confirm_response, target_id, t.tmux_target)
        dlg.present()

    def _on_kill_confirm_response(self, dialog, response_id, target_id: int, tmux_target: str):
        dialog.close()
        if response_id == Gtk.ResponseType.OK:
            kill_target(tmux_target, confirmed=True)
            self.store.hide_target(target_id)
            self.selection.selected.discard(target_id)
            self.refresh(discover=True)

    # ---------- grouping ----------

    def _chain_link(self) -> None:
        selected = [tid for tid in self.row_order if tid in self.selection.selected]
        if not selected:
            return
        self._input_dialog(
            "Chain-Link",
            "New berth name",
            lambda v: self._create_linked(v, selected),
            default="New Berth",
        )

    def _create_linked(self, name: str, ids: list[int]) -> None:
        berth_id = link_targets_to_new_berth(
            self.store, name.strip() or "New Berth", ids, self.config.colors.berth_default
        )
        self.selected_berth_id = berth_id
        self.refresh()

    def _unlink_selected(self) -> None:
        if self.selection.selected:
            unlink_targets(self.store, list(self.selection.selected))
            self.refresh()

    def _on_drop_to_berth(self, _drop, value, _x, _y, berth_id: int | None):
        try:
            tid = int(value)
        except (TypeError, ValueError):
            return False
        ids = list(self.selection.selected) if tid in self.selection.selected else [tid]
        if berth_id is None:
            unlink_targets(self.store, ids)
        else:
            move_targets_to_berth(self.store, berth_id, ids)
        self.refresh()
        return True

    def _on_drop_on_tile(self, _drop, value, _x, _y, dest_id: int, berth_id: int | None):
        try:
            tid = int(value)
        except (TypeError, ValueError):
            return False
        if tid == dest_id:
            return False
        src = self._target_by_id(tid)
        if src is None:
            return False
        if src.berth_id != berth_id:
            ids = list(self.selection.selected) if tid in self.selection.selected else [tid]
            move_targets_to_berth(self.store, berth_id, ids)
            self.refresh()
            return True
        siblings = [t.id for t in self._visible_targets() if t.berth_id == berth_id]
        if tid in siblings:
            siblings.remove(tid)
        idx = siblings.index(dest_id)
        siblings.insert(idx, tid)
        reorder_within_berth(self.store, siblings)
        self.refresh()
        return True

    def _select_berth_tvs(self, berth_id: int) -> None:
        ids = [t.id for t in self._visible_targets() if t.berth_id == berth_id]
        if not ids:
            return
        self.selection.selected = set(ids)
        self.selection.anchor_index = self.row_order.index(ids[0]) if ids[0] in self.row_order else None
        self._select_berth(berth_id)
        self._apply_selection()
        self._save_ui_state()

    def _unlink_berth_targets(self, berth_id: int) -> None:
        ids = [t.id for t in self.store.list_targets(include_hidden=False) if t.berth_id == berth_id]
        if ids:
            unlink_targets(self.store, ids)
            self.refresh()

    def _select_ungrouped_tvs(self) -> None:
        ids = [t.id for t in self._visible_targets() if t.berth_id is None]
        if not ids:
            return
        self.selection.selected = set(ids)
        self.selection.anchor_index = self.row_order.index(ids[0]) if ids[0] in self.row_order else None
        self.selected_berth_id = None
        self._apply_selection()
        self._save_ui_state()

    def _delete_berth(self, berth_id: int) -> None:
        if self.selected_berth_id == berth_id:
            self.selected_berth_id = None
        self.store.delete_berth(berth_id)
        self.refresh()

    def _move_berth(self, berth_id: int, delta: int) -> None:
        ids = [int(r["id"]) for r in self.store.list_berths()]
        if berth_id not in ids:
            return
        i = ids.index(berth_id)
        j = i + delta
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self.store.set_berth_sort_orders(ids)
        self.refresh()

    def _toggle_berth_collapse(self, berth_id: int) -> None:
        if berth_id in self.collapsed:
            self.collapsed.remove(berth_id)
        else:
            self.collapsed.add(berth_id)
        self._save_ui_state()
        self.refresh()

    # ---------- colors ----------

    def _color_target_berth(self) -> int | None:
        if self.selected_berth_id is not None:
            return self.selected_berth_id
        berths = {
            t.berth_id for t in self._visible_targets() if t.id in self.selection.selected
        }
        berths.discard(None)
        return berths.pop() if len(berths) == 1 else None

    def _on_palette_pick(self, _btn, color: str) -> None:
        berth_id = self._color_target_berth()
        if berth_id is not None:
            self.store.set_berth_color(berth_id, color)
            self.refresh()

    def _prompt_custom_color(self) -> None:
        berth_id = self._color_target_berth()
        if berth_id is not None:
            self._prompt_berth_color(berth_id)

    def _prompt_berth_color(self, berth_id: int) -> None:
        chooser = Gtk.ColorChooserDialog(title="Berth Color", transient_for=self, modal=True)

        def on_resp(dialog, resp):
            if resp == Gtk.ResponseType.OK:
                self.store.set_berth_color(berth_id, _rgba_to_hex(dialog.get_rgba()))
                self.refresh()
            dialog.close()

        chooser.connect("response", on_resp)
        chooser.present()

    # ---------- dialogs ----------

    def _prompt_create_berth(self) -> None:
        self._input_dialog(
            "Create Berth + TV", "Berth name", self._create_berth, default="New Berth"
        )

    def _create_berth(self, name: str) -> None:
        berth_name = name.strip()
        if berth_name:
            berth_id = self.store.create_berth(berth_name, self.config.colors.berth_default)
            self._create_tv_in_berth(berth_id, display_name=berth_name)

    def _prompt_rename_berth(self, berth_id: int) -> None:
        self._input_dialog(
            "Rename Berth", "New name", lambda v: self._rename_berth(berth_id, v)
        )

    def _prompt_rename_ungrouped(self) -> None:
        self._input_dialog(
            "Rename Ungrouped",
            "Section name",
            lambda v: self._rename_berth(None, v),
            default=self._berth_name(None),
        )

    def _rename_berth(self, berth_id: int | None, name: str) -> None:
        if name.strip():
            if berth_id is None:
                self.ungrouped_name = name.strip()
                self.store.set_setting("ui.ungrouped_name", self.ungrouped_name)
            else:
                self.store.rename_berth(berth_id, name.strip())
            self.refresh()

    def _prompt_rename_target(self, target_id: int) -> None:
        target = self._target_by_id(target_id)
        default = self._target_title(target) if target is not None else ""
        self._input_dialog(
            "Rename TV", "Display name", lambda v: self._rename_target(target_id, v), default=default
        )

    def _rename_target(self, target_id: int, name: str) -> None:
        if name.strip():
            self.store.rename_target(target_id, name.strip())
            self.refresh()

    def _inherit_berth_name(self) -> None:
        target = self._active_target()
        if target is None or target.berth_id is None:
            return
        self._rename_target(target.id, self._berth_name(target.berth_id))

    def _prompt_move_target(self, target_id: int) -> None:
        berths = self.store.list_berths()
        dlg = Gtk.Dialog(title="Move To Berth", transient_for=self, modal=True)
        box = dlg.get_content_area()
        combo = Gtk.DropDown.new_from_strings(["Ungrouped"] + [str(b["name"]) for b in berths])
        box.append(combo)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Move", Gtk.ResponseType.OK)

        def on_resp(d, resp):
            if resp == Gtk.ResponseType.OK:
                idx = combo.get_selected()
                ids = (
                    list(self.selection.selected)
                    if target_id in self.selection.selected
                    else [target_id]
                )
                if idx == 0:
                    unlink_targets(self.store, ids)
                else:
                    move_targets_to_berth(self.store, int(berths[idx - 1]["id"]), ids)
                self.refresh()
            d.close()

        dlg.connect("response", on_resp)
        dlg.present()

    def _input_dialog(self, title: str, placeholder: str, on_submit, default: str = "") -> None:
        dlg = Gtk.Dialog(title=title, transient_for=self, modal=True)
        box = dlg.get_content_area()
        ent = Gtk.Entry()
        ent.set_placeholder_text(placeholder)
        ent.set_text(default)
        box.append(ent)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("OK", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        ent.connect("activate", lambda *_: dlg.response(Gtk.ResponseType.OK))

        def on_resp(d, resp):
            if resp == Gtk.ResponseType.OK:
                on_submit(ent.get_text())
            d.close()

        dlg.connect("response", on_resp)
        dlg.present()

        def focus_entry():
            ent.grab_focus()
            if default:
                ent.select_region(0, -1)
            else:
                ent.set_position(-1)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(focus_entry)

    def _error_dialog(self, message: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.OK,
            message_type=Gtk.MessageType.ERROR,
            text=message,
        )
        dlg.connect("response", lambda d, _r: d.close())
        dlg.present()

    # ---------- hover preview ----------

    def _on_tile_hover_enter(self, _motion, _x, _y, target_id: int):
        if target_id in self.hover_timers:
            GLib.source_remove(self.hover_timers[target_id])
        self.hover_timers[target_id] = GLib.timeout_add(
            self.config.ui.hover_preview_delay_ms, self._show_hover_preview, target_id
        )

    def _on_tile_hover_leave(self, _motion, target_id: int):
        timer = self.hover_timers.pop(target_id, None)
        if timer is not None:
            GLib.source_remove(timer)
        tile = self.tile_rows.get(target_id)
        if tile is not None:
            tile.set_tooltip_text(None)

    def _show_hover_preview(self, target_id: int):
        self.hover_timers.pop(target_id, None)
        tile = self.tile_rows.get(target_id)
        if tile is None:
            return False
        text, _updated = self.store.get_preview(target_id)
        if text:
            tail = "\n".join(text.splitlines()[-self.config.preview.lines :])
        else:
            tail = "(no output)"
        tile.set_tooltip_text(tail)
        return False

    # ---------- polling / previews ----------

    def _on_poll(self):
        self.store.upsert_discovered_targets(discover_tmux_targets())
        self.health_banner.set_visible(not tmux_server_running())
        self._refresh_previews()
        if self._structure_snapshot() != self._snapshot:
            self.refresh()
        else:
            statuses = {t.id: t.status for t in self.store.list_targets(include_hidden=False)}
            for tid, minimap in self.minimaps.items():
                text, _updated = self.store.get_preview(tid)
                minimap.update(statuses.get(tid, "dead"), text)
            self._render_meta(self._active_target())
        return GLib.SOURCE_CONTINUE

    def _refresh_previews(self) -> None:
        min_interval = self.config.preview.refresh_min_interval_ms
        for t in self.store.list_targets(include_hidden=False):
            if t.status != "alive":
                continue
            _text, updated = self.store.get_preview(t.id)
            if updated is not None:
                age_ms = (datetime.now(UTC) - updated.replace(tzinfo=UTC)).total_seconds() * 1000
                if age_ms < min_interval:
                    continue
            lines = capture_last_lines(t.tmux_target, PREVIEW_CAPTURE_LINES)
            if lines:
                clipped = [ln[: self.config.preview.max_line_chars] for ln in lines]
                self.store.set_preview(t.id, "\n".join(clipped))

    # ---------- right panel ----------

    def _render_meta(self, target: TargetRow | None) -> None:
        count = len(self.selection.selected)
        if target is None:
            self.active_chip_label.set_text("No Active TV")
            _set_widget_border(self.active_chip, UNGROUPED_COLOR)
            _set_widget_fg(self.active_chip_label, UNGROUPED_COLOR)
            self.inherit_btn.set_sensitive(False)
            self.meta_line.set_text("")
            self.preview_label.set_text("Select a TV in the Harbor to preview it here.")
            self._sync_vte_terminal(None)
            return
        color = self._berth_color(target.berth_id)
        title = self._target_title(target)
        if count > 1:
            title = f"{title}  (+{count - 1} selected)"
        self.active_chip_label.set_text(title)
        _set_widget_border(self.active_chip, color)
        _set_widget_fg(self.active_chip_label, color)
        self.inherit_btn.set_sensitive(target.berth_id is not None)
        self.meta_line.set_text(
            f"{target.tmux_target}  ·  {target.status}  ·  {self._berth_name(target.berth_id)}"
        )
        text, _updated = self.store.get_preview(target.id)
        if target.status != "alive":
            shown = "(tmux target is dead)"
            if text:
                shown += "\n\nLast captured output:\n" + text
            self.preview_label.set_text(shown)
        else:
            self.preview_label.set_text(text or "(no output captured yet)")
        self._sync_vte_terminal(target if target.status == "alive" else None)

    def _sync_vte_terminal(self, target: TargetRow | None) -> None:
        if self.vte_terminal is None:
            return
        new_target = target.tmux_target if target is not None else None
        if new_target == self.vte_target:
            return
        self._stop_vte_child()
        self.vte_target = new_target
        if new_target is None:
            self.vte_terminal.reset(True, True)
            return
        self.vte_terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,
            attach_argv_for_target(new_target),
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            self._on_vte_spawned,
        )
        GLib.idle_add(self._focus_terminal)

    def _on_vte_spawned(self, terminal, pid, *args) -> None:
        if isinstance(pid, int) and pid > 0:
            self.vte_child_pid = pid
            terminal.watch_child(pid)

    def _on_vte_child_exited(self, _terminal, _status) -> None:
        self.vte_child_pid = None

    def _on_vte_selection_changed(self, terminal) -> None:
        # Copy-on-select: mirror the highlight into the real clipboard so it
        # can be pasted anywhere, not just via X11 primary middle-click. tmux
        # owns mouse-driven selection now (enable_mouse_selection), so this
        # only fires for Shift+drag, which bypasses tmux and asks VTE for its
        # own local selection instead.
        if terminal.get_has_selection():
            terminal.copy_clipboard_format(Vte.Format.TEXT)
            # If the user had scrolled up (wheel) before Shift-dragging, the
            # pane may still be in copy-mode; release it now that they've
            # copied what they wanted. No-op if it wasn't in a mode.
            if self.vte_target is not None:
                exit_copy_mode(self.vte_target)

    def _on_vte_right_click(self, gesture, _n_press, _x, _y) -> None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if self.vte_terminal is not None:
            self.vte_terminal.grab_focus()
            self.vte_terminal.paste_clipboard()

    def _stop_vte_child(self) -> None:
        if self.vte_child_pid is None:
            return
        try:
            os.kill(self.vte_child_pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        self.vte_child_pid = None

    def _on_attach_clicked(self, _btn) -> None:
        target = self._active_target()
        if target is not None and not launch_target(self.config, target.tmux_target):
            self._error_dialog("Failed to launch terminal. Check [terminal] command in config.")

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.query = entry.get_text()
        self.refresh()

    def _apply_mono_font_size(self) -> None:
        font_desc = Pango.FontDescription.from_string(
            f"{self.config.ui.mono_font_family} {self.mono_font_size}"
        )
        if self.vte_terminal is not None:
            self.vte_terminal.set_font(font_desc)
        _widget_css(self.preview_label, f"font-size:{self.mono_font_size}px;")

    def _change_mono_font_size(self, delta: int) -> None:
        self.mono_font_size = max(8, min(40, self.mono_font_size + delta))
        self.store.set_setting("ui.mono_font_size", str(self.mono_font_size))
        self._apply_mono_font_size()

    def _reset_mono_font_size(self) -> None:
        self.mono_font_size = self.config.ui.mono_font_size
        self.store.set_setting("ui.mono_font_size", str(self.mono_font_size))
        self._apply_mono_font_size()

    def _focus_terminal(self) -> None:
        if self.vte_terminal is not None:
            self.vte_terminal.set_input_enabled(True)
            self.vte_terminal.grab_focus()

    # ---------- css / persistence ----------

    def _load_css(self) -> None:
        if self.config.ui.theme == "dark":
            theme = {
                "bg": "#0e1116",
                "sidebar": "#12151c",
                "surface": "#1a1e27",
                "surface_hover": "#212633",
                "surface_alt": "#2a3040",
                "fg": "#e8ebf2",
                "muted": "#8b93a5",
                "border": "#262c39",
                "border_strong": "#3c4457",
                "monitor_bg": "#0a0d12",
                "term_bg": "#0a0d12",
                "term_fg": "#c9e8d6",
                "button_bg": "#1d222d",
                "selection_bg": "rgba(88, 133, 246, 0.16)",
                "danger_bg": "rgba(239, 68, 68, 0.12)",
                "danger_fg": "#f87171",
                "menu_bg": "#1c212b",
                "menu_hover": "#2b3242",
                "shadow": "rgba(0, 0, 0, 0.35)",
            }
        else:
            theme = {
                "bg": "#f2f4f8",
                "sidebar": "#f8f9fc",
                "surface": "#ffffff",
                "surface_hover": "#f1f4f9",
                "surface_alt": "#e8ecf3",
                "fg": "#1a202c",
                "muted": "#66718a",
                "border": "#dde3ec",
                "border_strong": "#aeb9cb",
                "monitor_bg": "#f7f9fc",
                "term_bg": "#101623",
                "term_fg": "#c9e8d6",
                "button_bg": "#ffffff",
                "selection_bg": "rgba(37, 99, 235, 0.10)",
                "danger_bg": "rgba(220, 38, 38, 0.08)",
                "danger_fg": "#dc2626",
                "menu_bg": "#ffffff",
                "menu_hover": "#eef2f8",
                "shadow": "rgba(15, 23, 42, 0.12)",
            }
        css = """
        window {
            background: %(bg)s;
            color: %(fg)s;
            font-family: '%(font)s';
            font-size: %(size)dpx;
        }

        paned > separator {
            background: %(border)s;
            min-width: 6px;
        }
        paned > separator:hover {
            background: %(border_strong)s;
        }

        .harbor {
            background: %(sidebar)s;
            border-right: 1px solid %(border)s;
            padding: 16px 14px 14px 14px;
        }
        .harbor-top { min-height: 36px; }
        .hdr {
            color: %(fg)s;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }

        button {
            background: %(button_bg)s;
            color: %(fg)s;
            border: 1px solid %(border)s;
            border-radius: 9px;
            padding: 6px 10px;
            min-height: 30px;
            box-shadow: none;
            transition: background 120ms ease, border-color 120ms ease;
        }
        button:hover {
            background: %(surface_hover)s;
            border-color: %(border_strong)s;
        }
        button:active {
            background: %(surface_alt)s;
        }
        .icon-button, .utility-button {
            min-width: 32px;
            min-height: 32px;
            padding: 0;
            color: %(muted)s;
        }
        .icon-button:hover, .utility-button:hover {
            color: %(fg)s;
        }
        .accent-button, .primary-button {
            background: %(selection)s;
            color: #ffffff;
            border-color: %(selection)s;
            font-weight: 600;
        }
        .accent-button:hover, .primary-button:hover {
            background: shade(%(selection)s, 1.15);
            border-color: shade(%(selection)s, 1.15);
            color: #ffffff;
        }
        .primary-button { padding-left: 16px; padding-right: 16px; }

        .search-box {
            background: %(surface)s;
            color: %(fg)s;
            border: 1px solid %(border)s;
            border-radius: 9px;
            min-height: 36px;
            transition: border-color 120ms ease;
        }
        .search-box:focus-within {
            border-color: %(selection)s;
            box-shadow: 0 0 0 3px alpha(%(selection)s, 0.18);
        }
        .search-box image { color: %(muted)s; }
        .harbor-scroll {
            background: transparent;
            border: 0;
        }

        .berth-section { margin-top: 4px; }
        .berth-header { min-height: 30px; }
        .berth-name {
            font-size: 13px;
            font-weight: 700;
            padding: 4px 8px;
            border-radius: 7px;
        }
        .berth-name.berth-selected {
            background: %(selection_bg)s;
        }
        .berth-name-edit {
            background: %(surface)s;
            color: %(fg)s;
            border: 1px solid %(selection)s;
            border-radius: 7px;
            padding: 3px 8px;
        }
        .berth-count {
            background: %(surface_alt)s;
            color: %(muted)s;
            border: none;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 10px;
            font-weight: 700;
            min-width: 34px;
        }
        .berth-move-btn {
            background: transparent;
            border-color: transparent;
            color: %(muted)s;
            min-width: 20px;
            min-height: 20px;
            padding: 0;
            border-radius: 6px;
        }
        .berth-move-btn:hover {
            background: %(surface_hover)s;
            color: %(fg)s;
        }
        .berth-add-tv {
            min-width: 28px;
            min-height: 28px;
            padding: 0;
            background: transparent;
            border-color: transparent;
            color: %(muted)s;
        }
        .berth-add-tv:hover {
            background: %(surface_hover)s;
            color: %(fg)s;
        }

        .tv-tile {
            background: %(surface)s;
            border: 1px solid %(border)s;
            border-radius: 12px;
            padding: 10px;
            box-shadow: 0 1px 3px %(shadow)s;
            transition: background 120ms ease, border-color 120ms ease;
        }
        .tv-tile:hover {
            background: %(surface_hover)s;
            border-color: %(border_strong)s;
        }
        .tv-tile.selected {
            background: %(selection_bg)s;
            border-color: %(selection)s;
        }
        .tile-hit { min-height: 76px; }
        .monitor {
            background: %(monitor_bg)s;
            border: 1px solid %(border)s;
            border-radius: 10px;
        }
        .tile-detail { margin-top: 4px; }
        .tv-name {
            color: %(fg)s;
            font-size: 13px;
            font-weight: 600;
        }
        .tv-target {
            color: %(muted)s;
            font-family: '%(mono)s';
            font-size: 11px;
        }
        .tv-status {
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 1px;
        }
        .status-dot {
            border-radius: 999px;
            margin-top: 5px;
        }
        .tile-action {
            background: transparent;
            border-color: transparent;
            min-width: 26px;
            min-height: 24px;
            padding: 0;
            border-radius: 7px;
        }
        .tile-action:hover {
            background: %(surface_alt)s;
            border-color: transparent;
        }
        .open-action { color: %(selection)s; }
        .close-action { color: %(muted)s; }
        .kill-action { color: %(danger_fg)s; }
        .kill-action:hover { background: %(danger_bg)s; }

        .palette {
            background: %(surface)s;
            border: 1px solid %(border)s;
            border-radius: 12px;
            padding: 8px;
        }
        .swatch-btn {
            background: transparent;
            border-color: transparent;
            min-width: 30px;
            min-height: 30px;
            padding: 3px;
            border-radius: 8px;
            color: %(muted)s;
        }
        .swatch-btn:hover {
            background: %(surface_hover)s;
            border-color: transparent;
        }
        .swatch {
            border: 1px solid alpha(%(fg)s, 0.25);
            border-radius: 999px;
        }
        .meta { background: %(bg)s; }
        .active-chip {
            border: 1px solid %(dim)s;
            border-radius: 14px;
            background: %(surface)s;
            box-shadow: 0 1px 3px %(shadow)s;
        }
        .active-chip-label {
            font-size: 17px;
            font-weight: 700;
        }
        .chip-action {
            background: transparent;
            border-color: transparent;
            color: %(muted)s;
            min-width: 26px;
            min-height: 26px;
            padding: 0;
            border-radius: 7px;
        }
        .chip-action:hover {
            background: %(surface_hover)s;
            color: %(fg)s;
        }
        .chip-action:disabled {
            color: alpha(%(muted)s, 0.4);
        }
        .meta-line {
            color: %(muted)s;
            font-family: '%(mono)s';
            font-size: 12px;
        }
        .term-frame {
            border: 1px solid %(border)s;
            border-radius: 14px;
            background: %(term_bg)s;
            box-shadow: 0 2px 8px %(shadow)s;
        }
        .term-text {
            font-family: '%(mono)s';
            font-size: %(mono_size)dpx;
            color: %(term_fg)s;
            padding: 14px;
        }
        .health-banner {
            background: %(danger_bg)s;
            color: %(danger_fg)s;
            border: 1px solid alpha(%(danger_fg)s, 0.4);
            font-weight: 600;
            padding: 6px 10px;
            border-radius: 9px;
        }

        popover,
        popover.menu,
        popover > contents,
        popover.menu > contents,
        popover.openberth-menu > contents,
        .openberth-menu > contents {
            background-color: %(menu_bg)s;
            color: %(fg)s;
            border: 1px solid %(border_strong)s;
            border-radius: 12px;
            box-shadow: 0 8px 24px %(shadow)s;
        }
        popover > contents,
        popover.menu > contents,
        popover.openberth-menu > contents,
        .openberth-menu > contents {
            padding: 6px;
        }
        .openberth-menu-box {
            background-color: %(menu_bg)s;
            padding: 6px;
        }
        popover *,
        popover label,
        popover modelbutton,
        popover modelbutton label,
        popover button,
        popover button label,
        popover.openberth-menu *,
        .openberth-menu * {
            color: %(fg)s;
        }
        popover modelbutton,
        popover button,
        popover.openberth-menu modelbutton,
        popover.openberth-menu button,
        .openberth-menu modelbutton,
        .openberth-menu button {
            background-color: transparent;
            color: %(fg)s;
            border-color: transparent;
            border-radius: 8px;
            padding: 7px 10px;
        }
        .openberth-menu-item {
            min-height: 30px;
            min-width: 180px;
        }
        popover modelbutton label,
        popover button label,
        popover.openberth-menu modelbutton label,
        popover.openberth-menu button label,
        .openberth-menu modelbutton label,
        .openberth-menu button label {
            color: %(fg)s;
        }
        popover modelbutton:hover,
        popover button:hover,
        popover.openberth-menu modelbutton:hover,
        popover.openberth-menu button:hover,
        .openberth-menu modelbutton:hover,
        .openberth-menu button:hover {
            background-color: %(menu_hover)s;
            color: %(fg)s;
        }
        popover modelbutton:disabled,
        popover modelbutton:disabled label,
        popover button:disabled,
        popover button:disabled label,
        popover.openberth-menu modelbutton:disabled,
        popover.openberth-menu modelbutton:disabled label,
        popover.openberth-menu button:disabled,
        popover.openberth-menu button:disabled label,
        .openberth-menu modelbutton:disabled,
        .openberth-menu modelbutton:disabled label,
        .openberth-menu button:disabled,
        .openberth-menu button:disabled label {
            color: %(muted)s;
        }
        """ % {
            **theme,
            "font": self.config.ui.font_family,
            "size": self.config.ui.font_size,
            "selection": self.config.colors.selection,
            "dim": UNGROUPED_COLOR,
            "mono": self.config.ui.mono_font_family,
            "mono_size": self.config.ui.mono_font_size,
        }
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(css)
        else:
            provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _load_ui_state(self) -> None:
        pos = self.store.get_setting("ui.paned_position")
        if pos and pos.isdigit():
            self.paned.set_position(int(pos))
        selected = self.store.get_setting("ui.selected_target_id")
        if selected and selected.isdigit():
            self.selection.selected = {int(selected)}
        berth = self.store.get_setting("ui.selected_berth_id")
        if berth and berth.isdigit():
            self.selected_berth_id = int(berth)
        ungrouped_name = self.store.get_setting("ui.ungrouped_name")
        if ungrouped_name and ungrouped_name.strip():
            self.ungrouped_name = ungrouped_name.strip()
        collapsed = self.store.get_setting("ui.collapsed_berths")
        if collapsed:
            self.collapsed = {int(p) for p in collapsed.split(",") if p.isdigit()}
        mono_size = self.store.get_setting("ui.mono_font_size")
        if mono_size and mono_size.isdigit():
            self.mono_font_size = max(8, min(40, int(mono_size)))
        self._apply_mono_font_size()

    def _save_ui_state(self) -> None:
        self.store.set_setting("ui.paned_position", str(self.paned.get_position()))
        if self.selection.selected:
            self.store.set_setting(
                "ui.selected_target_id", str(next(iter(self.selection.selected)))
            )
        self.store.set_setting(
            "ui.selected_berth_id",
            "" if self.selected_berth_id is None else str(self.selected_berth_id),
        )
        self.store.set_setting(
            "ui.collapsed_berths", ",".join(str(b) for b in sorted(self.collapsed))
        )
        self.store.set_setting("ui.mono_font_size", str(self.mono_font_size))
        self.store.set_setting("ui.ungrouped_name", self.ungrouped_name)

    def _on_close_request(self, *_args):
        self._stop_vte_child()
        self._save_ui_state()
        return False


def _iter_children(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        yield child
        child = nxt


def _menu_popover(menu: Gio.MenuModel, action_owner: Gio.ActionMap) -> Gtk.Popover:
    pop = Gtk.Popover()
    pop.add_css_class("openberth-menu")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("openberth-menu-box")
    _append_menu_items(box, menu, pop, action_owner)
    pop.set_child(box)
    return pop


def _append_menu_items(
    box: Gtk.Box, menu: Gio.MenuModel, popover: Gtk.Popover, action_owner: Gio.ActionMap
) -> None:
    for i in range(menu.get_n_items()):
        section = menu.get_item_link(i, "section")
        if section is not None:
            if box.get_first_child() is not None:
                box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            _append_menu_items(box, section, popover, action_owner)
            continue

        label_variant = menu.get_item_attribute_value(i, "label", None)
        action_variant = menu.get_item_attribute_value(i, "action", None)
        if label_variant is None or action_variant is None:
            continue

        label = Gtk.Label(label=str(label_variant.unpack()), xalign=0)
        label.add_css_class("openberth-menu-label")
        button = Gtk.Button()
        button.add_css_class("openberth-menu-item")
        button.set_child(label)
        button.set_halign(Gtk.Align.FILL)
        button.set_hexpand(True)
        action_name = str(action_variant.unpack())
        if action_name.startswith("win."):
            action_name = action_name.removeprefix("win.")
        target = menu.get_item_attribute_value(i, "target", None)
        action = action_owner.lookup_action(action_name)
        button.set_sensitive(action is not None)
        button.connect("clicked", _on_menu_item_clicked, popover, action, target)
        box.append(button)


def _on_menu_item_clicked(
    _button: Gtk.Button, popover: Gtk.Popover, action: Gio.Action | None, target: GLib.Variant | None
) -> None:
    popover.popdown()
    if action is not None:
        action.activate(target)


def _widget_css(widget: Gtk.Widget, rule: str) -> None:
    provider = Gtk.CssProvider()
    css = f"*{{{rule}}}"
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(css)
    else:
        provider.load_from_data(css.encode("utf-8"))
    widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _set_widget_bg(widget: Gtk.Widget, color: str) -> None:
    _widget_css(widget, f"background:{color};")


def _set_widget_fg(widget: Gtk.Widget, color: str) -> None:
    _widget_css(widget, f"color:{color};")


def _set_widget_border(widget: Gtk.Widget, color: str) -> None:
    _widget_css(widget, f"border-color:{color};")


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    r = int(max(0, min(1, rgba.red)) * 255)
    g = int(max(0, min(1, rgba.green)) * 255)
    b = int(max(0, min(1, rgba.blue)) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


class OpenBerthApp(Gtk.Application):
    def __init__(self, db_path: str, config_path: str | None):
        super().__init__(application_id=APPLICATION_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.db_path = db_path
        self.config_path = config_path

    def do_activate(self):
        store = Store(self.db_path)
        store.init()
        config = load_config(self.config_path)
        window = OpenBerthWindow(self, store, config)
        window.present()


def run_ui(db_path: str | None = None, config_path: str | None = None) -> int:
    db = db_path or str(Path.home() / ".openberth.db")
    return OpenBerthApp(db, config_path).run([])


def main() -> int:
    parser = argparse.ArgumentParser(prog="openberth-ui")
    parser.add_argument("--db", default=str(Path.home() / ".openberth.db"))
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    return run_ui(args.db, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
