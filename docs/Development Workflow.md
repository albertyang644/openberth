---
tags:
  - openberth/development
---

# Development Workflow

Use [[README|OpenBerth README]] for setup and common commands.

Important checks:

- `python3 -m unittest discover -s tests -p "test_*.py"`
- `/usr/bin/python3 -m pip wheel . -w /tmp/openberth-wheel --no-deps --no-build-isolation`
- `openberth --help`
- `openberth-ui --help`

Development topics:

- [[Architecture]] explains where behavior lives.
- [[User Model]] explains product expectations.
- [[Desktop Launch]] explains package and KDE launcher behavior.
- [[openberth_specifications|UI specification]] is the source for interaction design.
