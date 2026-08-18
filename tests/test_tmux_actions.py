from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from openberth.config import OpenBerthConfig, TerminalConfig
from openberth.tmux_actions import (
    attach_argv_for_target,
    create_target,
    enable_mouse_selection,
    exit_copy_mode,
    format_terminal_command,
    kill_target,
    pop_out_target,
    scroll_target_history,
    set_session_status_style,
    spawn_tmux_session,
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

        view = "__openberth_view_456_123"
        self.assertEqual(argv, ["tmux", "attach", "-t", view])
        run_mock.assert_any_call(
            ["tmux", "new-session", "-d", "-t", "forex", "-s", view],
            check=False,
            text=True,
            capture_output=True,
        )
        run_mock.assert_any_call(["tmux", "select-window", "-t", f"{view}:2"], check=False)
        run_mock.assert_any_call(["tmux", "select-pane", "-t", f"{view}:2.1"], check=False)

    @patch("openberth.tmux_actions.time.time_ns", return_value=123)
    @patch("openberth.tmux_actions.os.getpid", return_value=456)
    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    @patch("openberth.tmux_actions._session_has_attached_client", return_value=True)
    def test_ephemeral_view_name_cannot_carry_session_name_into_hook(
        self, _attached, run_mock, _pid, _time
    ) -> None:
        # tmux allows ";" and quotes in session names, and the client-detached
        # hook body is parsed by tmux as a command string -- so the view name
        # must never embed the session name.
        evil = 'x; run-shell "touch /tmp/pwned"'
        attach_argv_for_target(f"{evil}:2.1")

        hook_bodies = [
            call.args[0][-1]
            for call in run_mock.call_args_list
            if len(call.args) and "set-hook" in call.args[0]
        ]
        self.assertTrue(hook_bodies, "expected a client-detached hook to be set")
        for body in hook_bodies:
            self.assertNotIn("run-shell", body)
            self.assertNotIn(";", body)
            self.assertEqual(body, "kill-session -t __openberth_view_456_123")

    @patch("openberth.tmux_actions.shutil.which", return_value="/usr/bin/systemd-run")
    @patch("openberth.tmux_actions.tmux_server_running", return_value=False)
    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_server_is_started_outside_the_app_cgroup(self, run_mock, _up, _which) -> None:
        # A server started with a plain subprocess inherits OpenBerth's systemd
        # app scope and is killed with it, taking every session down.
        spawn_tmux_session(["tmux", "new-session", "-d", "-s", "demo"])

        argv = run_mock.call_args_list[0].args[0]
        self.assertEqual(argv[0], "systemd-run")
        self.assertIn("--user", argv)
        self.assertIn("--scope", argv)
        # the session-creating command itself must be inside the scope
        self.assertEqual(argv[-5:], ["tmux", "new-session", "-d", "-s", "demo"])
        self.assertEqual(len(run_mock.call_args_list), 1)

    @patch("openberth.tmux_actions.shutil.which", return_value="/usr/bin/systemd-run")
    @patch("openberth.tmux_actions.tmux_server_running", return_value=True)
    @patch("openberth.tmux_actions.subprocess.run")
    def test_existing_server_is_not_wrapped(self, run_mock, _up, _which) -> None:
        # server is already up (and already in whatever scope started it), so
        # this call cannot create one -- no need to pay for systemd-run
        spawn_tmux_session(["tmux", "new-session", "-d", "-s", "demo"])
        run_mock.assert_called_once_with(
            ["tmux", "new-session", "-d", "-s", "demo"], check=False
        )

    @patch("openberth.tmux_actions.shutil.which", return_value=None)
    @patch("openberth.tmux_actions.tmux_server_running", return_value=False)
    @patch("openberth.tmux_actions.subprocess.run", return_value=Mock(returncode=0))
    def test_falls_back_to_plain_start_without_systemd_run(self, run_mock, _up, _which) -> None:
        spawn_tmux_session(["tmux", "new-session", "-d", "-s", "demo"])
        run_mock.assert_called_once_with(
            ["tmux", "new-session", "-d", "-s", "demo"], check=False
        )

    @patch("openberth.tmux_actions.shutil.which", return_value="/usr/bin/systemd-run")
    @patch("openberth.tmux_actions.tmux_server_running", return_value=False)
    @patch("openberth.tmux_actions.subprocess.run")
    def test_falls_back_to_plain_start_when_systemd_run_fails(self, run_mock, _up, _which) -> None:
        run_mock.side_effect = [Mock(returncode=1, stderr=b""), Mock(returncode=0)]
        spawn_tmux_session(["tmux", "new-session", "-d", "-s", "demo"])
        self.assertEqual(
            run_mock.call_args_list[-1].args[0], ["tmux", "new-session", "-d", "-s", "demo"]
        )

    @patch("openberth.tmux_actions.spawn_tmux_session")
    def test_create_target_spawns_through_the_scope_wrapper(self, spawn_mock) -> None:
        spawn_mock.return_value = Mock(returncode=1)
        create_target("demo")
        spawn_mock.assert_called_once_with(["tmux", "new-session", "-d", "-s", "demo"])

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

    @patch("openberth.tmux_actions.shutil.which", side_effect=lambda c: "/usr/bin/xclip")
    @patch("openberth.tmux_actions.os.environ", {})
    @patch(
        "openberth.tmux_actions.subprocess.run",
        return_value=Mock(returncode=0, stdout=""),
    )
    def test_enable_mouse_selection_scopes_mouse_and_unbinds_menu(
        self, run_mock, _which
    ) -> None:
        enable_mouse_selection("forex")
        run_mock.assert_any_call(
            ["tmux", "set-option", "-t", "forex", "mouse", "on"], check=False
        )
        run_mock.assert_any_call(
            ["tmux", "unbind-key", "-T", "root", "MouseDown3Pane"], check=False
        )
        run_mock.assert_any_call(
            ["tmux", "set-option", "-g", "copy-command", "xclip -selection clipboard -i"],
            check=False,
        )

    @patch("openberth.tmux_actions.shutil.which", side_effect=lambda c: "/usr/bin/xclip")
    @patch("openberth.tmux_actions.os.environ", {})
    @patch(
        "openberth.tmux_actions.subprocess.run",
        return_value=Mock(returncode=0, stdout="my-own-copier\n"),
    )
    def test_enable_mouse_selection_does_not_clobber_existing_copy_command(
        self, run_mock, _which
    ) -> None:
        enable_mouse_selection("forex")
        for call in run_mock.call_args_list:
            self.assertNotIn("-g", call.args[0])


if __name__ == "__main__":
    unittest.main()
