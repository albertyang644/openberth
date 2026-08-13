---
tags:
  - openberth/desktop
  - openberth/kde
---

# Desktop Launch

OpenBerth is installable as a local Python package and launchable from KDE.

Related files are documented in [[README|OpenBerth README]]. The installed commands are:

- `openberth`
- `openberth-ui`
- `openberth-install-desktop`

The desktop launcher uses the same application identity as the GTK app:

- Application id: `com.openberth.app`
- Desktop file: `com.openberth.app.desktop`
- Icon name: `com.openberth.app`

That shared identity lets KDE connect the application launcher, taskbar icon, and running window.

Related notes:

- [[OpenBerth Map]]
- [[Architecture]]
- [[Development Workflow]]
