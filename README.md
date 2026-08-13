# OpenBerth

A GTK4 desktop app for organizing running tmux sessions as visual "TVs" grouped into
"berths" — like browser tabs for your terminal workspace.

OpenBerth is not a terminal manager and does not own shell processes. tmux remains the
source of truth; OpenBerth stores metadata that makes tmux targets easy to find, group,
preview, launch, and (only when explicitly confirmed) kill.

## Concept

- A **TV** represents one tmux target (`session:window.pane`).
- A **berth** is a named, color-coded group of TVs.
- The **Harbor** is the left-side list of berths and TVs, with live activity minimaps.
- The right panel embeds a real terminal (VTE) attached to the active TV.
- **Closing** a TV hides it from OpenBerth without touching tmux; **killing** a target
  is destructive and always requires confirmation.

## Features

- tmux discovery with periodic polling and alive/dead status tracking
- Chain-link selected TVs into berths; unlink; drag-and-drop; Photoshop-style
  multi-select (click, Ctrl-toggle, Shift-range)
- Berth color palette + custom picker; colors drive the Harbor accents **and each
  session's tmux status bar**, so popped-out terminals match
- Cairo-drawn activity minimaps and live text previews from captured pane output
- Embedded VTE terminal with copy-on-select and right-click paste
- Pop out TVs into wezterm windows, docked as tabs per berth
- Search across names, targets, and berths (Ctrl+P); restore closed TVs (Ctrl+Shift+T)
- SQLite persistence (`~/.openberth.db`); CLI that works without GTK

## Install

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-vte-3.91 libgtk-4-1 tmux wezterm
/usr/bin/python3 -m pip install --user --break-system-packages .
openberth-install-desktop   # KDE/GNOME launcher entry + icon
```

Use the system Python for the UI — conda/miniconda Pythons do not see the
apt-installed GTK bindings.

## Run

```bash
openberth-ui                # GTK UI
openberth --discover        # CLI, no GTK needed
openberth                   # list known TVs
```

Configuration is read from `~/.openberth.toml` (see [.openberth.toml](.openberth.toml)
for a documented example: theme, fonts, colors, poll interval, terminal command).

## Development

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

Docs live in [docs/](docs/): [architecture](docs/Architecture.md),
[user model](docs/User%20Model.md), [UI specification](docs/openberth_specifications.md),
[quickstart](docs/quickstart.md). The original design sketch is in
[assets/ui-mockup.png](assets/ui-mockup.png).

## License

[MIT](LICENSE.md)
