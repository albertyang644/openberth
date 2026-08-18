---
tags:
  - openberth/development
---

# Development Workflow

Use [OpenBerth README](README.md) for setup and common commands.

Important checks:

- `python3 -m unittest discover -s tests -p "test_*.py"`
- `/usr/bin/python3 -m pip wheel . -w /tmp/openberth-wheel --no-deps --no-build-isolation`
- `openberth --help`
- `openberth-ui --help`

Development topics:

- [Architecture](architecture.md) explains where behavior lives.
- [User Model](user-model.md) explains product expectations.
- [Desktop Launch](desktop-launch.md) explains package and KDE launcher behavior.
- [UI specification](openberth-specifications.md) is the source for interaction design.
