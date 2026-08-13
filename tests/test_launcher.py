from __future__ import annotations

import unittest
from unittest.mock import patch

from openberth.config import OpenBerthConfig, TerminalConfig, ViewerConfig
from openberth.launcher import can_launch, launch_target


class LauncherTests(unittest.TestCase):
    def test_launch_disabled_by_default(self) -> None:
        cfg = OpenBerthConfig()
        self.assertFalse(can_launch(cfg))

    @patch("openberth.launcher.subprocess.Popen")
    def test_launch_enabled(self, popen_mock) -> None:
        cfg = OpenBerthConfig(
            viewer=ViewerConfig(type="external_terminal", attach_enabled=True),
            terminal=TerminalConfig(command='echo attach {target}'),
        )
        ok = launch_target(cfg, "forex:1")
        self.assertTrue(ok)
        popen_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

