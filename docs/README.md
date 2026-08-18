# OpenBerth

OpenBerth is a GTK desktop app for organizing running tmux targets as visual "TVs" grouped into "berths". It is not a terminal manager and it does not own shell processes. tmux remains the source of truth; OpenBerth stores metadata that makes those tmux targets easier to find, group, preview, launch, close from the workspace, and safely kill when explicitly requested.

Obsidian map: [[OpenBerth Map]].
Design source: [[openberth_specifications|UI specification]].

## Concept

Most tmux workflows become hard to scan once many sessions, windows, and panes are active. OpenBerth gives that workspace a visual layer:

- A TV represents one tmux target.
- A berth is a named group of TVs.
- The Harbor is the left-side list of TVs and berths.
- The right panel shows the active TV preview or embedded terminal.
- Closing a TV hides it from OpenBerth without touching tmux.
- Killing a target is destructive and requires confirmation.

The mental model is close to browser tabs plus desktop selection. You can select TVs, chain-link them into berths, color-code groups, pop out a terminal, and restore recently closed TVs.

## Goals

- Make active tmux work visible at a glance.
- Let users group tmux targets without changing tmux structure.
- Keep destructive behavior explicit and confirmed.
- Provide a normal desktop application experience on Linux/KDE.
- Keep the CLI useful when GTK is unavailable.

## Non-Goals

- OpenBerth does not replace tmux.
- OpenBerth does not supervise or restart shell processes.
- OpenBerth does not hide tmux concepts from automation or configuration.
- OpenBerth does not kill tmux targets or restructure your sessions, windows,
  and panes unless the user asks it to. Attaching a TV does set two tmux options
  on that session (see Embedded Terminal below); nothing else is written.

## Target Audience

OpenBerth is for Linux users who already use tmux and want a visual organizer for many running panes. It is especially useful for operators, developers, traders, automation-heavy users, and anyone who keeps several terminal workflows alive at once.

The project currently assumes a desktop Linux environment with GTK4. KDE integration is supported through an installable desktop launcher.

## Requirements

- Python 3.11 or newer
- tmux
- GTK4 Python bindings for the graphical UI
- wezterm for the default docked pop-out workflow
- KDE/desktop launcher integration expects `~/.local/bin` on your session PATH

On Debian/Ubuntu-style systems:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-vte-3.91 libgtk-4-1 tmux wezterm
```

Use the system Python for the GTK UI. Conda and miniconda Python builds often cannot see GTK typelibs installed by the OS package manager.

## Install

From the repository root:

```bash
/usr/bin/python3 -m pip install --user --break-system-packages .
```

This installs:

```bash
openberth
openberth-ui
openberth-install-desktop
```

To install the desktop launcher and icon:

```bash
openberth-install-desktop
```

OpenBerth should then appear in your desktop application launcher. On KDE, launch it once and pin the running application if you want it on the taskbar.

## Run

Start the graphical app:

```bash
openberth-ui
```

Run the UI through the CLI entry point (optionally with an explicit config):

```bash
/usr/bin/python3 -m openberth.app --ui
/usr/bin/python3 -m openberth.app --ui --config .openberth.toml
```

List known TVs from the CLI:

```bash
openberth
```

Refresh discovery:

```bash
openberth --discover
```

OpenBerth stores local app state in:

```text
~/.openberth.db
```

If a config path is not supplied, OpenBerth reads:

```text
~/.openberth.toml
```

## Core UI Workflow

1. Start tmux sessions and panes as usual.
2. Open OpenBerth.
3. Use the Harbor to select TVs.
4. Chain-link selected TVs into a berth.
5. Rename and color-code berths.
6. Use the right panel to preview or interact with the active TV.
7. Pop out a TV when you want a separate terminal window.
8. Close TVs to hide them from the OpenBerth workspace without killing tmux.
9. Restore recently closed TVs with Ctrl+Shift+T.

## Selection

OpenBerth uses familiar desktop selection behavior:

- Click selects one TV.
- Ctrl-click toggles a TV in or out of selection.
- Shift-click selects a range.
- Up and Down move keyboard selection.
- Enter opens the active TV.
- Delete closes the active TV.
- Shift+Delete asks to kill the active tmux target.

## Berths

A berth is a metadata group. Moving a TV into a berth does not move tmux windows or panes. It only changes how OpenBerth organizes the target.

You can:

- Create a new berth.
- Chain-link selected TVs into a berth.
- Add a new TV directly into a berth.
- Rename a berth.
- Rename the special ungrouped section.
- Select all TVs in a berth.
- Change berth color. Colors drive the Harbor accents and each session's tmux status bar.
- Collapse or expand a berth.
- Reorder berths, either one slot at a time (Move Up / Move Down) or by picking a
  berth up with its hand icon and carrying it to a new position.
- Unlink all TVs, which empties the berth but keeps it.
- Delete Berth, which returns its TVs to the ungrouped section.
- Delete Berth and All TVs, which kills the underlying tmux targets first. This is
  destructive and requires confirmation.

## TV Actions

TVs expose these common actions:

- Open: attach or focus the TV.
- Pop Out: launch a separate terminal attached to the tmux target.
- Rename: set a display name for the TV.
- Move To Berth: place the TV into a group.
- Copy tmux Target: copy the raw tmux target string.
- Copy Display Name: copy the TV's display name.
- Close TV: hide it from OpenBerth while tmux keeps running.
- Kill Target: kill the underlying tmux pane after confirmation.

## Embedded Terminal

With the default `embedded_vte` viewer, the right panel attaches a real terminal to the
active TV. Two things are worth knowing:

- **tmux owns the mouse.** Attaching sets `mouse on` for that session and unbinds the
  root `MouseDown3Pane` menu, so drag-to-edge autoscroll, copy-on-select, and
  right-click paste behave like a normal terminal window. `Alt`+right-click is left
  bound as an escape hatch to tmux's own menu. These are the only tmux options
  OpenBerth writes on its own.
- **Second attach to a busy session.** tmux's current window is per-session, not
  per-client, so attaching a second TV from the same session would yank the other
  client's view. OpenBerth instead attaches through a throwaway grouped session named
  `__openberth_view_*`, which shares every window and pane but keeps its own current-
  window pointer. It self-destructs on detach and is filtered out of discovery, so it
  never appears as a phantom TV.

## Configuration

Example:

```toml
[viewer]
type = "embedded_vte"
attach_enabled = false

[discovery]
poll_seconds = 5

[terminal]
command = '/usr/bin/wezterm start -- tmux attach -t {session} \; select-window -t {window_target} \; select-pane -t {target}'
dock_mode = "berth_dock"

[ui]
theme = "dark"
font_family = "Sans"
font_size = 14
mono_font_family = "Monospace"
mono_font_size = 15
hover_preview_enabled = true
hover_preview_delay_ms = 2000

[preview]
lines = 4
max_line_chars = 160
refresh_min_interval_ms = 1000
```

The terminal command may use:

- `{target}` for the full tmux target, such as `work:1.0`
- `{session}` for the tmux session
- `{window_target}` for the session and window portion

The default terminal command uses wezterm; edit `[terminal] command` in the
config for your terminal of choice.

## CLI Reference

```bash
openberth --discover
openberth --launch work:1.0
openberth --pop-out work:1.0
openberth --kill work:1.0 --confirm-kill
openberth --close-tv 12
openberth --restore-tv
```

Use `openberth --help` and `openberth-ui --help` for the current command-line surface.

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

Build a wheel:

```bash
/usr/bin/python3 -m pip wheel . -w /tmp/openberth-wheel --no-deps --no-build-isolation
```

Important modules:

- `openberth/discovery.py`: tmux discovery.
- `openberth/config.py`: config loading and defaults.
- `openberth/models.py`: core dataclasses.
- `openberth/store.py`: SQLite persistence.
- `openberth/grouping.py`: berth membership operations.
- `openberth/selection.py`: desktop-style selection model.
- `openberth/tmux_actions.py`: explicit tmux actions.
- `openberth/launcher.py`: terminal launch behavior.
- `openberth/ui_app.py`: GTK application.
- `openberth/desktop.py`: desktop launcher installation.

`openberth/ui_mock.py` is the earlier GTK4 visual workflow prototype with mock
TV data:

```bash
/usr/bin/python3 -m openberth.ui_mock
```

## Documentation Map

- `README.md` (repository root): GitHub-facing overview.
- `docs/README.md`: main human-facing guide (this file).
- `docs/quickstart.md`: short setup and workflow checklist.
- `docs/openberth_specifications.md`: interaction specification notes.
- `docs/User Model.md`: product model notes.
- `docs/Architecture.md`: architecture notes.
- `docs/Desktop Launch.md`: desktop integration notes.
- `docs/Development Workflow.md`: development notes.
- `docs/OpenBerth Map.md`: note index.
