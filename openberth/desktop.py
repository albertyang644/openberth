from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

APP_ID = "com.openberth.app"
APP_NAME = "OpenBerth"


def _default_command_path(command: str) -> str:
    found = shutil.which(command)
    if found:
        return found

    local_bin = Path.home() / ".local" / "bin" / command
    if local_bin.exists():
        return str(local_bin)

    return command


def _desktop_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\ ")


def desktop_entry(exec_path: str | None = None) -> str:
    command = _desktop_escape(exec_path or _default_command_path("openberth-ui"))
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            f"Name={APP_NAME}",
            "Comment=Organize and launch tmux targets",
            f"Exec={command}",
            f"Icon={APP_ID}",
            "Terminal=false",
            "Categories=Utility;GTK;",
            "StartupNotify=true",
            f"StartupWMClass={APP_ID}",
            "SingleMainWindow=true",
            "",
        ]
    )


def install_desktop(
    applications_dir: Path | None = None,
    icons_dir: Path | None = None,
    exec_path: str | None = None,
    update_caches: bool = True,
) -> tuple[Path, Path]:
    applications = applications_dir or Path.home() / ".local" / "share" / "applications"
    icons = icons_dir or Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    applications.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)

    desktop_path = applications / f"{APP_ID}.desktop"
    icon_path = icons / f"{APP_ID}.svg"

    desktop_path.write_text(desktop_entry(exec_path), encoding="utf-8")
    desktop_path.chmod(0o644)

    icon_resource = resources.files("openberth").joinpath("resources", f"{APP_ID}.svg")
    with resources.as_file(icon_resource) as icon_source:
        shutil.copyfile(icon_source, icon_path)
    icon_path.chmod(0o644)

    if update_caches:
        _update_caches(applications, icons)

    return desktop_path, icon_path


def _update_caches(applications_dir: Path, icons_dir: Path) -> None:
    commands = [
        ("update-desktop-database", str(applications_dir)),
        ("gtk-update-icon-cache", "-q", str(icons_dir.parents[2])),
    ]
    for cmd in commands:
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    kde_service = shutil.which("kbuildsycoca6") or shutil.which("kbuildsycoca5")
    if kde_service:
        subprocess.run([kde_service], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the OpenBerth KDE/desktop launcher.")
    parser.add_argument(
        "--exec",
        dest="exec_path",
        default=None,
        help="path to the openberth-ui executable for the desktop launcher",
    )
    parser.add_argument("--no-cache-update", action="store_true", help="skip desktop/icon cache refresh")
    args = parser.parse_args()

    desktop_path, icon_path = install_desktop(
        exec_path=args.exec_path,
        update_caches=not args.no_cache_update,
    )
    print(f"Installed desktop launcher: {desktop_path}")
    print(f"Installed icon: {icon_path}")
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("kde") >= 0:
        print("OpenBerth should now appear in the KDE application launcher.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
