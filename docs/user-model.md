---
tags:
  - openberth/product
  - openberth/ui
---

# User Model

The product model comes from [UI specification](openberth-specifications.md).

OpenBerth presents tmux targets as TVs. Users organize TVs into berths, select them with familiar desktop selection behavior, and launch or pop out terminals without OpenBerth owning tmux.

Related ideas:

- [Architecture](architecture.md) stores TVs and berths as metadata.
- [Desktop Launch](desktop-launch.md) makes OpenBerth feel like a normal KDE app.
- [Development Workflow](development-workflow.md) verifies behavior with focused tests.
- [OpenBerth README](README.md) documents how to run the app.

Important behaviors:

- TVs represent tmux targets.
- Berths group TVs without changing tmux.
- Closing a TV hides metadata only.
- Killing a target is destructive and requires confirmation.
- Pop out opens a terminal attached to the selected tmux target.
- The right panel embeds a terminal attached to the active TV, where tmux owns the mouse.
- Deleting a berth orphans its TVs; deleting a berth and all its TVs is destructive and confirmed.
