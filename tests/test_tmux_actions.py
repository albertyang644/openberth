from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from openberth.config import OpenBerthConfig, TerminalConfig
from openberth.tmux_actions import (
    attach_argv_for_target,
    exit_copy_mode,
    format_terminal_command,
    kill_target,
    pop_out_target,
    scroll_target_history,
    set_session_status_style,
)


class TmuxActionsTests(unittest.TestCase):
    @patch("openberth.tmux_actions.subprocess.Popen")
    def test_pop_out(self, popen_mock) -> None:
        cfg = OpenBerthConfig(terminal=TerminalConfig(command="echo attach {target}"))
        pop_out_target(cfg, "forex:1")
        popen_mock.assert_called_once()

    def test_format_terminal_command_exposes_target_parts(self) -> None:
        cmd = format_terminal_command(
            "attach {session} {window_target} {target}",
            "forex:2.1",
        )
        self.assertEqual(cmd, "attach forex forex:2 forex:2.1")

    @patch("openberth.tmux_actions.subprocess.run")
    @patch("openberth.tmux_actions._session_has_attached_client", return_value=False)
    def test_attach_argv_selects_target_when_session_is_unattached(
        self, _attached, run_mock
    ) -> None:
        self.assertEqual(attach_argv_for_target("forex:2.1"), ["tmux", "attach", "-t", "forex"])
        run_mock.assert_any_call(["tmux", "select-window", "-t", "forex:2"], check=False)
        run_mock.assert_any_call(["tmux", "select-pane", "-t", "forex:2.1"], check=False)

    @patch("openberth.tmux_actions.time.time_ns", return_value=123)
    @patch("openberth.tmux_actions.os.getpid", return_value=456)
    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    @patch("openberth.tmux_actions._session_has_attached_client", return_value=True)
    def test_attach_argv_uses_grouped_view_when_session_is_attached(
        self, _attached, run_mock, _pid, _time
    ) -> None:
        argv = attach_argv_for_target("forex:2.1")

        view = "__openberth_view_forex_456_123"
        self.assertEqual(argv, ["tmux", "attach", "-t", view])
        run_mock.assert_any_call(
            ["tmux", "new-session", "-d", "-t", "forex", "-s", view],
            check=False,
            text=True,
            capture_output=True,
        )
        run_mock.assert_any_call(["tmux", "select-window", "-t", f"{view}:2"], check=False)
        run_mock.assert_any_call(["tmux", "select-pane", "-t", f"{view}:2.1"], check=False)

    @patch("openberth.tmux_actions.subprocess.run")
    def test_kill_requires_confirmation(self, run_mock) -> None:
        self.assertFalse(kill_target("forex:1", confirmed=False))
        run_mock.assert_not_called()

    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_set_session_status_style_targets_session(self, run_mock) -> None:
        self.assertTrue(set_session_status_style("forex:2.1", "#3b82f6", "#f8fafc"))
        run_mock.assert_called_once_with(
            ["tmux", "set-option", "-t", "forex", "status-style", "bg=#3b82f6,fg=#f8fafc"],
            check=False,
        )

    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_scroll_up_enters_copy_mode_and_scrolls_history(self, run_mock) -> None:
        self.assertTrue(scroll_target_history("forex:2.1", up=True, lines=10))
        run_mock.assert_called_once_with(
            [
                "tmux",
                "copy-mode",
                "-e",
                "-t",
                "forex:2.1",
                ";",
                "send-keys",
                "-X",
                "-t",
                "forex:2.1",
                "-N",
                "10",
                "scroll-up",
            ],
            check=False,
        )

    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_scroll_down_uses_copy_mode_scroll_exit(self, run_mock) -> None:
        self.assertTrue(scroll_target_history("forex:2.1", up=False))
        run_mock.assert_called_once_with(
            [
                "tmux",
                "send-keys",
                "-X",
                "-t",
                "forex:2.1",
                "-N",
                "5",
                "scroll-down",
            ],
            check=False,
        )

    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_exit_copy_mode_sends_cancel(self, run_mock) -> None:
        self.assertTrue(exit_copy_mode("forex:2.1"))
        run_mock.assert_called_once_with(
            ["tmux", "send-keys", "-X", "-t", "forex:2.1", "cancel"], check=False
        )


if __name__ == "__main__":
    unittest.main()
