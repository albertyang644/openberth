---
tags:
  - openberth/desktop
  - openberth/kde
---

# Desktop Launch

OpenBerth is installable as a local Python package and launchable from KDE.

Related files are documented in [OpenBerth README](README.md). The installed commands are:

- `openberth`
- `openberth-ui`
- `openberth-install-desktop`

The desktop launcher uses the same application identity as the GTK app:

- Application id: `com.openberth.app`
- Desktop file: `com.openberth.app.desktop`
- Icon name: `com.openberth.app`

That shared identity lets KDE connect the application launcher, taskbar icon, and running window.

Related notes:

- [OpenBerth Map](openberth-map.md)
- [Architecture](architecture.md)
- [Development Workflow](development-workflow.md)
