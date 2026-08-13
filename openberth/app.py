from __future__ import annotations

import argparse
from pathlib import Path

from openberth.config import load_config
from openberth.discovery import discover_tmux_targets
from openberth.launcher import launch_target
from openberth.selection import SelectionModel
from openberth.store import Store
from openberth.tmux_actions import kill_target, pop_out_target


def bootstrap(db_path: str, config_path: str | None) -> tuple[Store, SelectionModel]:
    store = Store(db_path)
    store.init()
    store.upsert_discovered_targets(discover_tmux_targets())
    return store, SelectionModel()


def main() -> int:
    parser = argparse.ArgumentParser(prog="openberth")
    parser.add_argument("--db", default=str(Path.home() / ".openberth.db"))
    parser.add_argument("--config", default=None)
    parser.add_argument("--ui", action="store_true", help="run GTK UI")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--launch", default=None, help="tmux target string to launch")
    parser.add_argument("--pop-out", default=None, help="tmux target string to pop out")
    parser.add_argument("--kill", default=None, help="tmux target string to kill")
    parser.add_argument("--confirm-kill", action="store_true")
    parser.add_argument("--close-tv", type=int, default=None, help="close TV by target id")
    parser.add_argument("--restore-tv", action="store_true")
    args = parser.parse_args()

    if args.ui:
        try:
            from openberth.ui_app import run_ui
        except (ImportError, ValueError) as exc:
            print(f"GTK4 bindings unavailable: {exc}")
            print("Install them with: sudo apt install python3-gi gir1.2-gtk-4.0 libgtk-4-1")
            print("Then run with the system python: /usr/bin/python3 -m openberth.app --ui")
            return 1
        return int(run_ui(args.db, args.config))

    store, _sel = bootstrap(args.db, args.config)
    cfg = load_config(args.config)

    if args.discover:
        store.upsert_discovered_targets(discover_tmux_targets())
        print("Discovery complete.")

    if args.launch:
        launched = launch_target(cfg, args.launch)
        print("Launch requested." if launched else "Launch disabled by config.")

    if args.pop_out:
        pop_out_target(cfg, args.pop_out)
        print("Pop-out requested.")

    if args.kill:
        ok = kill_target(args.kill, confirmed=args.confirm_kill)
        print("Kill requested." if ok else "Kill blocked (missing confirmation or tmux error).")

    if args.close_tv is not None:
        store.close_tv(args.close_tv)
        print(f"Closed TV {args.close_tv}.")

    if args.restore_tv:
        restored = store.restore_last_closed_tv()
        print(f"Restored TV {restored}." if restored is not None else "No closed TVs to restore.")

    if not any(
        [args.discover, args.launch, args.pop_out, args.kill, args.close_tv is not None, args.restore_tv]
    ):
        berth_names = {b["id"]: b["name"] for b in store.list_berths()}
        for t in store.list_targets(include_hidden=False):
            name = t.display_name or t.tmux_target
            berth = "Ungrouped" if t.berth_id is None else berth_names.get(t.berth_id, str(t.berth_id))
            print(f"{name} [{t.status}] ({berth})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
