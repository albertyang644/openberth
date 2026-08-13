from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openberth.desktop import APP_ID, desktop_entry, install_desktop


class DesktopIntegrationTests(unittest.TestCase):
    def test_desktop_entry_uses_openberth_identity(self):
        entry = desktop_entry("/tmp/openberth-ui")

        self.assertIn(f"Icon={APP_ID}", entry)
        self.assertIn(f"StartupWMClass={APP_ID}", entry)
        self.assertIn("Exec=/tmp/openberth-ui", entry)

    def test_install_desktop_writes_launcher_and_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop_path, icon_path = install_desktop(
                applications_dir=root / "applications",
                icons_dir=root / "icons" / "hicolor" / "scalable" / "apps",
                exec_path="/tmp/openberth-ui",
                update_caches=False,
            )

            self.assertTrue(desktop_path.exists())
            self.assertTrue(icon_path.exists())
            self.assertIn("Name=OpenBerth", desktop_path.read_text(encoding="utf-8"))
            self.assertGreater(icon_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
