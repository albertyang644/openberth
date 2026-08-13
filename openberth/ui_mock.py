from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402


@dataclass
class Tile:
    index: int
    selected: bool = False


@dataclass
class Berth:
    name: str
    color: str
    tiles: list[Tile]


BERTHS = [
    Berth("Ollama", "#d97706", [Tile(1, True), Tile(2)]),
    Berth("Forex", "#2ea44f", [Tile(1), Tile(2), Tile(3)]),
]


class MonitorTile(Gtk.Frame):
    def __init__(self, tile: Tile, color: str):
        super().__init__()
        self.set_css_classes(["monitor-tile"])
        if tile.selected:
            self.add_css_class("selected")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_hexpand(False)
        row.set_halign(Gtk.Align.START)
        self.set_child(row)

        screen = Gtk.Box()
        screen.set_size_request(74, 64)
        screen.set_css_classes(["monitor-screen"])
        row.append(screen)

        idx = Gtk.Label(label=str(tile.index), xalign=0)
        idx.set_css_classes(["tile-index"])
        idx.set_name(color)
        row.append(idx)


class BerthColumn(Gtk.Box):
    def __init__(self, berth: Berth):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_halign(Gtk.Align.START)
        self.set_css_classes(["berth-column"])

        band_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        band_row.set_halign(Gtk.Align.START)

        band = Gtk.Box()
        band.set_size_request(10, 152 if len(berth.tiles) == 2 else 230)
        band.set_css_classes(["berth-band"])
        band.set_name(berth.color)
        band_row.append(band)

        tiles_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for tile in berth.tiles:
            tiles_col.append(MonitorTile(tile, berth.color))
        band_row.append(tiles_col)
        self.append(band_row)

        name = Gtk.Label(label=berth.name, xalign=0)
        name.set_css_classes(["berth-name"])
        name.set_name(berth.color)
        self.append(name)


class SketchWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="OpenBerth - Sketch Mock")
        self.set_default_size(1024, 960)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_css_classes(["outer"])
        self.set_child(outer)

        frame = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        frame.set_css_classes(["root-frame"])
        outer.append(frame)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        left.set_css_classes(["preview-col"])
        frame.append(left)

        preview = Gtk.Label(label="Preview", xalign=0)
        preview.set_css_classes(["preview-title"])
        left.append(preview)

        for berth in BERTHS:
            left.append(BerthColumn(berth))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_hexpand(True)
        frame.append(right)

        chip = Gtk.Frame()
        chip.set_css_classes(["active-chip"])
        chip_box = Gtk.Box()
        chip_box.set_size_request(0, 72)
        chip.set_child(chip_box)
        chip_label = Gtk.Label(label="Ollama 1")
        chip_label.set_css_classes(["active-chip-label"])
        chip_box.append(chip_label)
        right.append(chip)

        term = Gtk.Frame()
        term.set_hexpand(True)
        term.set_vexpand(True)
        term.set_css_classes(["term-frame"])
        term_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        term.set_child(term_box)
        term_label = Gtk.Label(label="Term")
        term_label.set_css_classes(["term-title"])
        term_box.append(term_label)
        right.append(term)

        self._load_css()

    def _load_css(self) -> None:
        css = """
        window { background: #dcdcdc; color: #222; }
        .outer { padding: 18px; }
        .root-frame {
            background: #dcdcdc;
            border: 3px solid #2b2b2b;
            border-radius: 34px;
            padding: 18px;
        }
        .preview-col { min-width: 190px; }
        .preview-title { font-size: 34px; font-weight: 700; margin-bottom: 4px; }
        .berth-column { margin-top: 4px; }
        .berth-band { border-radius: 8px; }
        .berth-name { font-size: 34px; font-weight: 700; margin-left: 22px; }

        .monitor-tile {
            border: 3px solid #2b2b2b;
            border-radius: 22px;
            background: #efefef;
            padding: 6px;
            min-width: 96px;
        }
        .monitor-tile.selected { border-color: #1f6feb; }
        .monitor-screen {
            background: #f3f3f3;
            border: 0;
            border-radius: 12px;
        }
        .tile-index { font-size: 36px; font-weight: 700; }

        .active-chip {
            border: 3px solid #2ea44f;
            border-radius: 20px;
            background: transparent;
            min-height: 72px;
        }
        .active-chip-label { font-size: 42px; font-weight: 700; color: #2ea44f; }

        .term-frame {
            border: 3px solid #2b2b2b;
            border-radius: 34px;
            background: #dcdcdc;
            min-height: 640px;
        }
        .term-title { font-size: 42px; font-weight: 700; margin-top: 10px; }
        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        def paint_named(widget: Gtk.Widget) -> None:
            n = widget.get_name()
            if n and n.startswith("#"):
                cp = Gtk.CssProvider()
                cp.load_from_data(f"*{{color:{n}; background:{n};}}".encode("utf-8"))
                widget.get_style_context().add_provider(cp, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            c = widget.get_first_child()
            while c is not None:
                paint_named(c)
                c = c.get_next_sibling()

        paint_named(self)


class SketchApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.openberth.sketch", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        SketchWindow(self).present()


def run() -> int:
    return SketchApp().run([])


if __name__ == "__main__":
    raise SystemExit(run())

