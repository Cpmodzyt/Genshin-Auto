"""Unit tests for the parts of autoskip_dialogue that do not need a game.

Run with:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from random import Random
from unittest import mock

import autoskip_dialogue as app


class HotkeyTests(unittest.TestCase):
    def test_function_keys(self) -> None:
        self.assertEqual(app.parse_vk("f8", 0), 0x77)
        self.assertEqual(app.parse_vk("F12", 0), 0x7B)
        self.assertEqual(app.parse_vk("f1", 0), 0x70)
        self.assertEqual(app.parse_vk("f24", 0), 0x87)

    def test_letters_digits_and_specials(self) -> None:
        self.assertEqual(app.parse_vk("x", 0), ord("X"))
        self.assertEqual(app.parse_vk("5", 0), ord("5"))
        self.assertEqual(app.parse_vk("escape", 0), 0x1B)
        self.assertEqual(app.parse_vk("space", 0), 0x20)

    def test_hex_and_fallback(self) -> None:
        self.assertEqual(app.parse_vk("0x77", 0), 0x77)
        self.assertEqual(app.parse_vk("not-a-key", 0x99), 0x99)
        self.assertEqual(app.parse_vk("", 0x99), 0x99)

    def test_vk_name(self) -> None:
        self.assertEqual(app.vk_name(0x77), "F8")
        self.assertEqual(app.vk_name(0x7B), "F12")
        self.assertEqual(app.vk_name(ord("X")), "X")
        self.assertEqual(app.vk_name(0x1B), "Esc")


class ColourTests(unittest.TestCase):
    def test_color_close(self) -> None:
        self.assertTrue(app.color_close((236, 229, 216), (236, 229, 216), 0))
        self.assertTrue(app.color_close((240, 225, 210), (236, 229, 216), 16))
        self.assertFalse(app.color_close((0, 0, 0), (236, 229, 216), 16))
        self.assertFalse(app.color_close(None, (236, 229, 216), 16))

    def test_is_whiteish(self) -> None:
        self.assertTrue(app.is_whiteish((255, 255, 255)))
        self.assertTrue(app.is_whiteish((240, 238, 236)))
        self.assertFalse(app.is_whiteish((200, 200, 200)))
        self.assertFalse(app.is_whiteish(None))


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = app.Config(width=1920, height=1080)
        self.assertEqual(config.skip_interval, 1.0)
        self.assertEqual(config.start_vk, 0x77)
        self.assertEqual(config.pause_vk, 0x78)
        self.assertEqual(config.toggle_vk, 0x76)
        self.assertEqual(config.exit_vk, 0x7B)
        self.assertTrue(config.require_focus)
        self.assertTrue(config.humanize)

    def test_interval_is_clamped(self) -> None:
        config = app.Config(width=1920, height=1080, skip_interval=0.01)
        self.assertGreaterEqual(config.skip_interval, 0.2)
        self.assertGreaterEqual(config.min_interval, 0.2)

    def test_break_order_is_fixed(self) -> None:
        config = app.Config(width=1920, height=1080, break_min=9, break_max=2)
        self.assertLessEqual(config.break_min, config.break_max)

    def test_env_round_trip_has_expected_keys(self) -> None:
        config = app.Config(width=1920, height=1080)
        env = config.to_env()
        for key in ("WIDTH", "HEIGHT", "SKIP_INTERVAL", "START_KEY", "AUTOSTART"):
            self.assertIn(key, env)
        self.assertEqual(env["SKIP_INTERVAL"], "1.0")


class DelayTests(unittest.TestCase):
    def test_delay_stays_in_bounds(self) -> None:
        config = app.Config(width=1920, height=1080)
        rng = Random(1234)
        for _ in range(500):
            delay = app.next_delay(config, rng)
            self.assertGreaterEqual(delay, config.min_interval)
            self.assertLessEqual(
                delay, config.skip_interval + config.interval_jitter + 1e-9
            )

    def test_delay_without_humanize_is_exact(self) -> None:
        config = app.Config(width=1920, height=1080, humanize=False)
        self.assertEqual(app.next_delay(config, Random(1)), 1.0)


class LayoutTests(unittest.TestCase):
    def test_full_hd(self) -> None:
        layout = app.ScreenLayout(1920, 1080)
        points = layout.points("mnk")
        self.assertEqual(points["PLAYING_ICON_Y"], (84, 46))
        self.assertEqual(points["DIALOGUE_ICON_LOWER_Y"], (1301, 808))
        self.assertEqual(points["DIALOGUE_ICON_HIGHER_Y"], (1301, 790))
        self.assertEqual(points["LOADING_SCREEN_Y"], (1200, 700))

    def test_2k_scales(self) -> None:
        layout = app.ScreenLayout(2560, 1440)
        points = layout.points("mnk")
        self.assertEqual(points["PLAYING_ICON_Y"], (112, 61))
        self.assertEqual(points["DIALOGUE_ICON_LOWER_Y"], (1734, 1077))

    def test_2880x1800_uses_exact_override(self) -> None:
        layout = app.ScreenLayout(2880, 1800)
        points = layout.points("mnk")
        self.assertEqual(points["PLAYING_ICON_Y"], (126, 76))
        self.assertEqual(points["DIALOGUE_ICON_LOWER_Y"], (1947, 1370))
        self.assertEqual(points["DIALOGUE_ICON_HIGHER_Y"], (1947, 1260))

    def test_ultrawide_uses_wide_screen_table(self) -> None:
        layout = app.ScreenLayout(3440, 1440)
        self.assertFalse(layout.is_default_ratio())
        points = layout.points("mnk")
        self.assertEqual(points["PLAYING_ICON_Y"], (199, 61))
        self.assertGreater(points["DIALOGUE_ICON_LOWER_Y"][0], 2000)
        self.assertEqual(points["DIALOGUE_ICON_LOWER_Y"][1], 1080)

    def test_unknown_device_raises(self) -> None:
        layout = app.ScreenLayout(1920, 1080)
        with self.assertRaises(ValueError):
            layout.points("gamepad")


class HotkeyWatcherTests(unittest.TestCase):
    def test_callback_fires_once_on_key_down(self) -> None:
        calls: list[str] = []

        def fake_state(vk: int) -> int:
            return 0x8000 if vk == 0x77 else 0

        watcher = app.HotkeyWatcher({0x77: lambda: calls.append("start")}, 0.01)
        with mock.patch.object(
            app.win32api, "GetAsyncKeyState", side_effect=fake_state
        ):
            watcher.start()
            import time

            time.sleep(0.12)
            watcher.stop()

        self.assertEqual(calls, ["start"])


if __name__ == "__main__":
    unittest.main()
