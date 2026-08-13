---
tags:
  - openberth/architecture
---

# Architecture

OpenBerth keeps tmux and UI state separated. The app discovers tmux targets, persists metadata, and uses launch actions only when the user asks.

Main areas:

- Discovery keeps the known target list current.
- Store persists targets, berths, settings, and closed TVs.
- Selection handles single, Ctrl, and Shift selection behavior from [[User Model]].
- Grouping links selected TVs into berths.
- Launcher and tmux actions handle explicit terminal operations.
- UI app presents the GTK experience described in [[openberth_specifications|UI specification]].

Related notes:

- [[User Model]]
- [[Desktop Launch]]
- [[Development Workflow]]
- [[README|OpenBerth README]]

The package and desktop integration are described in [[Desktop Launch]].
