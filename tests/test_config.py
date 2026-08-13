from __future__ import annotations

import tempfile
import unittest

from openberth.config import load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_to_embedded_viewer(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".toml") as f:
            f.write("")
            f.flush()
            cfg = load_config(f.name)

        self.assertEqual(cfg.viewer.type, "embedded_vte")

    def test_extended_config_fields(self) -> None:
        data = """
[ui]
theme = "light"
font_family = "Inter"
font_size = 14
mono_font_family = "JetBrains Mono"
mono_font_size = 12
hover_preview_enabled = true
hover_preview_delay_ms = 1500

[preview]
lines = 5
max_line_chars = 100
refresh_min_interval_ms = 500

[colors]
selection = "#123456"
"""
        with tempfile.NamedTemporaryFile("w+", suffix=".toml") as f:
            f.write(data)
            f.flush()
            cfg = load_config(f.name)
        self.assertEqual(cfg.ui.theme, "light")
        self.assertEqual(cfg.ui.font_family, "Inter")
        self.assertEqual(cfg.preview.lines, 5)
        self.assertEqual(cfg.colors.selection, "#123456")


if __name__ == "__main__":
    unittest.main()
