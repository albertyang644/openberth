# OpenBerth Quickstart

## Install

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 libgtk-4-1 tmux wezterm
/usr/bin/python3 -m pip install --user --break-system-packages .
openberth-install-desktop
```

## Start

```bash
openberth-ui
```

If GTK cannot load, run the UI with system Python:

```bash
/usr/bin/python3 -m openberth.app --ui
```

## Daily Use

- Start and manage tmux normally.
- Open OpenBerth to discover running tmux targets.
- Select TVs with click, Ctrl-click, and Shift-click.
- Use the chain-link action to group selected TVs into a berth.
- Rename and color berths so work is easy to scan.
- Pop out a TV when you need a separate terminal.
- Close a TV to hide it without killing tmux.
- Restore closed TVs with Ctrl+Shift+T.
- Kill only when you intend to terminate the underlying tmux target.

## Useful Commands

```bash
openberth --discover
openberth
openberth --pop-out session:1.0
openberth --kill session:1.0 --confirm-kill
openberth --restore-tv
python -m pytest
```

## Files

- App database: `~/.openberth.db`
- Optional config: `~/.openberth.toml`
- Main docs: `docs/README.md`
