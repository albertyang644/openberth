---
tags:
  - openberth/product
  - openberth/ui
---

# User Model

The product model comes from [[openberth_specifications|UI specification]].

OpenBerth presents tmux targets as TVs. Users organize TVs into berths, select them with familiar desktop selection behavior, and launch or pop out terminals without OpenBerth owning tmux.

Related ideas:

- [[Architecture]] stores TVs and berths as metadata.
- [[Desktop Launch]] makes OpenBerth feel like a normal KDE app.
- [[Development Workflow]] verifies behavior with focused tests.
- [[README|OpenBerth README]] documents how to run the app.

Important behaviors:

- TVs represent tmux targets.
- Berths group TVs without changing tmux.
- Closing a TV hides metadata only.
- Killing a target is destructive and requires confirmation.
- Pop out opens a terminal attached to the selected tmux target.
- The right panel embeds a terminal attached to the active TV, where tmux owns the mouse.
- Deleting a berth orphans its TVs; deleting a berth and all its TVs is destructive and confirmed.
