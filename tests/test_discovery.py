import unittest

from openberth.discovery import _parse_tmux_line


class DiscoveryTests(unittest.TestCase):
    def test_parse_valid_line(self) -> None:
        t = _parse_tmux_line("forex:2.1")
        assert t is not None
        self.assertEqual(t.tmux_session, "forex")
        self.assertEqual(t.tmux_window, 2)
        self.assertEqual(t.tmux_pane, 1)
        self.assertEqual(t.tmux_target, "forex:2.1")

    def test_parse_invalid_line(self) -> None:
        self.assertIsNone(_parse_tmux_line("broken"))


if __name__ == "__main__":
    unittest.main()
