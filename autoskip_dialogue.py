"""
Genshin Impact - Dialogue Auto-Skip
===================================

A Windows-only, keyboard-and-mouse dialogue auto-skipper for Genshin Impact.

What it does
------------
* Watches a handful of screen pixels to figure out when a dialogue is running
  or when dialogue options are on screen.
* Presses your in-game "interact / continue" key on a human-like interval
  (1 second by default) to advance the dialogue.
* Only acts while the game window is in the foreground.
* Auto-detects the current screen resolution on every launch and fixes the
  saved ``.env`` automatically, so a stale config can never silently break
  detection again.

Controls (all configurable in ``.env``)
---------------------------------------
F8  - start
F9  - pause
F7  - toggle start/pause
F12 - quit

Test / debug helpers
--------------------
``python autoskip_dialogue.py --probe``
    Print resolution, foreground window and the RGB value of every detection
    pixel. Use this first if auto-skip "does nothing".

``python autoskip_dialogue.py --debug``
    Same information continuously while the program runs.

``python autoskip_dialogue.py --autostart``
    Start skipping immediately without waiting for F8.

Safety / fair-use notice
------------------------
Automation of any kind violates the Genshin Impact Terms of Service and can
get an account banned.  The "human-like" timings here only make the input
pattern less robotic; they do **not** hide the program from anti-cheat and
they do not make it safe.  Use at your own risk.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from threading import Event, Lock, Thread

# ---------------------------------------------------------------------------
# Optional / third-party imports with friendly error messages
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv, set_key
except ImportError:  # pragma: no cover - dependency check
    sys.exit("Missing dependency 'python-dotenv'. Run: pip install -r requirements.txt")

try:
    import pyautogui
except ImportError:  # pragma: no cover - dependency check
    sys.exit("Missing dependency 'pyautogui'. Run: pip install -r requirements.txt")

try:
    import win32api
    import win32gui
except ImportError:  # pragma: no cover - dependency check
    sys.exit("Missing dependency 'pywin32'. Run: pip install -r requirements.txt")


VERSION = "2.0.0"
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOG_PATH = BASE_DIR / "autoskip.log"

# ---------------------------------------------------------------------------
# DPI awareness
# ---------------------------------------------------------------------------
# Windows display scaling (125 %, 150 %, ...) makes GetSystemMetrics() report
# *logical* pixels while screen capture works in *physical* pixels.  Without
# this call the saved resolution and the detected pixel coordinates disagree
# on any scaled display, which is one of the most common "F8 does nothing"
# causes.  Must run before any coordinate is read.
# ---------------------------------------------------------------------------


def enable_dpi_awareness() -> None:
    """Make the process DPI aware so coordinates match captured pixels."""
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_dpi_awareness()
pyautogui.FAILSAFE = False  # a cornered mouse must not kill the skip loop


# ---------------------------------------------------------------------------
# Screen geometry helpers
# ---------------------------------------------------------------------------


def get_screen_size() -> tuple[int, int]:
    """Return the current primary screen size in physical pixels."""
    return int(win32api.GetSystemMetrics(0)), int(win32api.GetSystemMetrics(1))


def width_adjust(x: int, screen_width: int) -> int:
    """Scale an x value authored for 1920 px width to the current width."""
    return int(x / 1920 * screen_width)


def height_adjust(y: int, screen_height: int) -> int:
    """Scale a y value authored for 1080 px height to the current height."""
    return int(y / 1080 * screen_height)


def get_position_right(
    hdpos_x: int, doublehdpos_x: int, screen_width: int, extra: float
) -> int:
    """Position a pixel that is anchored to the right edge of the screen."""
    if screen_width <= 3840:  # above 4K an extra multiplier is needed
        extra = 0
    diff = doublehdpos_x - hdpos_x
    change_per_pixel = diff / 1920
    screen_diff = screen_width - 1920
    extra_pixels = screen_diff * (change_per_pixel + extra)
    return int(hdpos_x + extra_pixels)


def get_position_left(hdpos_x: int, doublehdpos_x: int, screen_width: int) -> int:
    """Position a pixel that is anchored to the left edge of the screen."""
    diff = doublehdpos_x - hdpos_x
    change_per_pixel = diff / 1920
    screen_diff = screen_width - 1920
    extra_pixels = screen_diff * change_per_pixel
    return int(hdpos_x + extra_pixels)


# ---------------------------------------------------------------------------
# Detection coordinates
# ---------------------------------------------------------------------------
# Every value is authored for a 1920x1080 (16:9) display and scaled at run
# time.  "default" is used for 16:9 screens, "wide_screen" for ultrawide,
# and an exact (width, height) key wins over both.
# ---------------------------------------------------------------------------

Coord = tuple
COORDS: dict[str, dict[object, dict[str, Coord]]] = {
    "mnk": {
        "default": {
            "PLAYING_ICON_X": ("width_adjust", 84),
            "PLAYING_ICON_Y": ("height_adjust", 46),
            "DIALOGUE_ICON_X": ("width_adjust", 1301),
            "DIALOGUE_ICON_LOWER_Y": ("height_adjust", 808),
            "DIALOGUE_ICON_HIGHER_Y": ("height_adjust", 790),
            "LOADING_SCREEN_X": ("width_adjust", 1200),
            "LOADING_SCREEN_Y": ("height_adjust", 700),
        },
        "wide_screen": {
            "PLAYING_ICON_X": ("get_position_left", 84, 230),
            "DIALOGUE_ICON_X": ("get_position_right", 1301, 2770, 0.02),
            "DIALOGUE_ICON_LOWER_Y": ("height_adjust", 810),
            "DIALOGUE_ICON_HIGHER_Y": ("height_adjust", 792),
        },
        (2880, 1800): {
            "PLAYING_ICON_X": ("static", 126),
            "DIALOGUE_ICON_X": ("static", 1947),
            "DIALOGUE_ICON_LOWER_Y": ("static", 1370),
            "DIALOGUE_ICON_HIGHER_Y": ("static", 1260),
        },
    },
    "gamepad": {},
}


class ScreenLayout:
    """Resolve authored detection coordinates for the current screen."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.res = (width, height)

    def is_default_ratio(self) -> bool:
        """True when the display is 16:9 (or not wider than 1920)."""
        return not (self.width > 1920 and self.height / self.width != 0.5625)

    def _table(self, device: str) -> dict[str, Coord]:
        device_table = COORDS.get(device)
        if not device_table:
            raise ValueError(
                f"Unsupported device '{device}'. Only 'mnk' is implemented."
            )
        base = device_table.get("default", {})
        if self.res in device_table:
            override = device_table[self.res]
        elif not self.is_default_ratio():
            override = device_table.get("wide_screen", {})
        else:
            override = {}
        return {**base, **override}

    def get(self, device: str, name: str) -> int:
        """Return the resolved pixel coordinate for a named detection point."""
        merged = self._table(device)
        if name not in merged:
            raise KeyError(f"Unknown detection point: {device}.{name}")
        spec = merged[name]
        kind = spec[0]
        if kind == "width_adjust":
            return width_adjust(spec[1], self.width)
        if kind == "height_adjust":
            return height_adjust(spec[1], self.height)
        if kind == "get_position_left":
            return min(get_position_left(spec[1], spec[2], self.width), 230)
        if kind == "get_position_right":
            return get_position_right(spec[1], spec[2], self.width, spec[3])
        if kind == "static":
            return int(spec[1])
        raise ValueError(f"Unknown coord handler '{kind}' for {device}.{name}")

    def points(self, device: str) -> dict[str, tuple[int, int]]:
        """Return every (x, y) detection point for the current screen."""
        table = self._table(device)
        out: dict[str, tuple[int, int]] = {}
        for name in table:
            if name.endswith("_X"):
                prefix = name[:-2]
                x = self.get(device, name)
                for suffix in ("_LOWER_Y", "_HIGHER_Y", "_Y"):
                    y_name = prefix + suffix
                    if y_name in table:
                        out[y_name] = (x, self.get(device, y_name))
        return out


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    """Runtime configuration, populated from ``.env`` plus auto-detection."""

    width: int
    height: int
    confirm_button: str = "f"
    device: str = "mnk"
    skip_interval: float = 1.0
    interval_jitter: float = 0.2
    min_interval: float = 0.85
    poll_interval: float = 0.05
    color_tolerance: int = 16
    pixel_radius: int = 1
    require_focus: bool = True
    window_title: str = "Genshin Impact"
    breaks_enabled: bool = True
    break_chance: float = 0.04
    break_min: float = 3.0
    break_max: float = 8.0
    humanize: bool = True
    fatigue_min: int = 10
    fatigue_max: int = 22
    fatigue_pause_min: float = 1.5
    fatigue_pause_max: float = 4.0
    start_key: str = "f8"
    pause_key: str = "f9"
    toggle_key: str = "f7"
    exit_key: str = "f12"
    autostart: bool = False
    max_session_minutes: float = 0.0
    log_to_file: bool = True

    # These are filled in after parsing hotkey strings.
    start_vk: int = field(init=False, repr=False)
    pause_vk: int = field(init=False, repr=False)
    toggle_vk: int = field(init=False, repr=False)
    exit_vk: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.skip_interval = max(0.2, self.skip_interval)
        self.min_interval = max(0.2, min(self.min_interval, self.skip_interval))
        self.interval_jitter = max(0.0, self.interval_jitter)
        self.color_tolerance = max(0, min(80, self.color_tolerance))
        self.pixel_radius = max(0, min(4, self.pixel_radius))
        self.break_chance = max(0.0, min(1.0, self.break_chance))
        if self.break_max < self.break_min:
            self.break_min, self.break_max = self.break_max, self.break_min
        self.confirm_button = self.confirm_button.strip().lower() or "f"
        self.window_title = self.window_title.strip() or "Genshin Impact"
        self.start_vk = parse_vk(self.start_key, 0x77)  # F8
        self.pause_vk = parse_vk(self.pause_key, 0x78)  # F9
        self.toggle_vk = parse_vk(self.toggle_key, 0x76)  # F7
        self.exit_vk = parse_vk(self.exit_key, 0x7B)  # F12

    def to_env(self) -> dict[str, str]:
        return {
            "WIDTH": str(self.width),
            "HEIGHT": str(self.height),
            "CONFIRM_BUTTON": self.confirm_button,
            "DEVICE": self.device,
            "SKIP_INTERVAL": str(self.skip_interval),
            "INTERVAL_JITTER": str(self.interval_jitter),
            "MIN_INTERVAL": str(self.min_interval),
            "COLOR_TOLERANCE": str(self.color_tolerance),
            "PIXEL_RADIUS": str(self.pixel_radius),
            "REQUIRE_FOCUS": str(self.require_focus).lower(),
            "WINDOW_TITLE": self.window_title,
            "BREAKS_ENABLED": str(self.breaks_enabled).lower(),
            "BREAK_CHANCE": str(self.break_chance),
            "BREAK_MIN": str(self.break_min),
            "BREAK_MAX": str(self.break_max),
            "HUMANIZE": str(self.humanize).lower(),
            "START_KEY": self.start_key,
            "PAUSE_KEY": self.pause_key,
            "TOGGLE_KEY": self.toggle_key,
            "EXIT_KEY": self.exit_key,
            "AUTOSTART": str(self.autostart).lower(),
            "MAX_SESSION_MINUTES": str(self.max_session_minutes),
            "LOG_TO_FILE": str(self.log_to_file).lower(),
        }


VK_SPECIAL: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "numlock": 0x90,
    "scrolllock": 0x91,
}


def parse_vk(value: str, fallback: int) -> int:
    """Turn a config string such as ``f8``, ``x`` or ``0x77`` into a VK code."""
    text = (value or "").strip().lower()
    if not text:
        return fallback
    if text.startswith("f") and text[1:].isdigit():
        number = int(text[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    if text in VK_SPECIAL:
        return VK_SPECIAL[text]
    if len(text) == 1 and text.isalnum():
        return ord(text.upper())
    try:
        code = int(text, 0)
    except ValueError:
        return fallback
    return code if 0 < code < 256 else fallback


def vk_name(vk: int) -> str:
    """Return a short display name for a virtual-key code."""
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    for name, code in VK_SPECIAL.items():
        if code == vk and len(name) > 1:
            return name.title()
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    return f"0x{vk:02X}"


class HotkeyWatcher:
    """Poll physical key state with GetAsyncKeyState.

    Genshin's anti-cheat can block global low-level keyboard hooks, which makes
    library-based hotkeys (pynput/keyboard) silently stop working while the
    game is focused.  Polling the OS key state does not install a hook, so it
    keeps working in that situation.
    """

    def __init__(self, bindings: dict[int, Callable[[], None]], interval: float = 0.03):
        self.bindings = dict(bindings)
        self.interval = max(0.01, interval)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._thread = Thread(target=self._run, name="hotkey-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        previous: set[int] = set()
        while not self._stop.is_set():
            try:
                down = {
                    vk for vk in self.bindings if win32api.GetAsyncKeyState(vk) & 0x8000
                }
            except Exception:
                down = set()
            for vk in down - previous:
                callback = self.bindings.get(vk)
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        pass
            previous = down
            time.sleep(self.interval)


def save_config(config: Config) -> None:
    """Persist the (auto-detected) configuration back to ``.env``."""
    try:
        if not ENV_PATH.exists():
            ENV_PATH.write_text("", encoding="utf-8")
        for key, value in config.to_env().items():
            set_key(str(ENV_PATH), key, value, quote_mode="never")
    except Exception as exc:  # pragma: no cover - filesystem dependent
        print(f"  [warn] Could not save .env: {exc}")


def load_config(no_save: bool = False) -> Config:
    """Load config, auto-detect the screen and repair stale values."""
    load_dotenv(ENV_PATH)

    detected_w, detected_h = get_screen_size()
    stored_w = _env_int("WIDTH", 0)
    stored_h = _env_int("HEIGHT", 0)

    stale = (stored_w, stored_h) != (detected_w, detected_h) and stored_w > 0
    width = detected_w or stored_w or 1920
    height = detected_h or stored_h or 1080

    config = Config(
        width=width,
        height=height,
        confirm_button=os.getenv("CONFIRM_BUTTON", "f") or "f",
        device=(os.getenv("DEVICE", "mnk") or "mnk").lower(),
        skip_interval=_env_float("SKIP_INTERVAL", 1.0),
        interval_jitter=_env_float("INTERVAL_JITTER", 0.2),
        min_interval=_env_float("MIN_INTERVAL", 0.85),
        poll_interval=_env_float("POLL_INTERVAL", 0.05),
        color_tolerance=_env_int("COLOR_TOLERANCE", 16),
        pixel_radius=_env_int("PIXEL_RADIUS", 1),
        require_focus=_env_bool("REQUIRE_FOCUS", True),
        window_title=os.getenv("WINDOW_TITLE", "Genshin Impact") or "Genshin Impact",
        breaks_enabled=_env_bool("BREAKS_ENABLED", True),
        break_chance=_env_float("BREAK_CHANCE", 0.04),
        break_min=_env_float("BREAK_MIN", 3.0),
        break_max=_env_float("BREAK_MAX", 8.0),
        humanize=_env_bool("HUMANIZE", True),
        start_key=os.getenv("START_KEY", "f8") or "f8",
        pause_key=os.getenv("PAUSE_KEY", "f9") or "f9",
        toggle_key=os.getenv("TOGGLE_KEY", "f7") or "f7",
        exit_key=os.getenv("EXIT_KEY", "f12") or "f12",
        autostart=_env_bool("AUTOSTART", False),
        max_session_minutes=_env_float("MAX_SESSION_MINUTES", 0.0),
        log_to_file=_env_bool("LOG_TO_FILE", True),
    )

    if stale:
        print(
            f"  [auto-fix] Saved resolution {stored_w}x{stored_h} does not match "
            f"this PC ({detected_w}x{detected_h}). Updating .env."
        )
    if not no_save:
        save_config(config)
    return config


# ---------------------------------------------------------------------------
# Foreground window / pixel helpers
# ---------------------------------------------------------------------------


def get_foreground_title() -> str:
    """Return the title of the foreground window (empty string on failure)."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def is_game_active(config: Config) -> bool:
    """True when the configured game window title is in the foreground."""
    if not config.require_focus:
        return True
    title = get_foreground_title().casefold()
    return config.window_title.casefold() in title


def get_pixel(x: int, y: int) -> tuple[int, int, int] | None:
    """Read one screen pixel, returning ``None`` if the read fails."""
    try:
        rgb = pyautogui.pixel(x, y)
        return int(rgb[0]), int(rgb[1]), int(rgb[2])
    except Exception:
        return None


def color_close(
    actual: tuple[int, int, int] | None,
    target: tuple[int, int, int],
    tolerance: int,
) -> bool:
    """Return True when every channel is within ``tolerance`` of target."""
    if actual is None:
        return False
    return all(abs(a - t) <= tolerance for a, t in zip(actual, target))


def is_whiteish(rgb: tuple[int, int, int] | None, threshold: int = 235) -> bool:
    """Return True for near-white pixels (dialogue option indicator)."""
    if rgb is None:
        return False
    return all(channel >= threshold for channel in rgb)


def region_has_color(
    x: int,
    y: int,
    radius: int,
    predicate: Callable[[tuple[int, int, int]], bool],
) -> bool:
    """Scan a small square around (x, y) and test every pixel.

    A single screen grab is used, so this stays cheap even at a few pixels of
    radius.  It compensates for tiny coordinate drift between game versions.
    """
    if radius <= 0:
        rgb = get_pixel(x, y)
        return rgb is not None and predicate(rgb)
    left = max(0, x - radius)
    top = max(0, y - radius)
    size = radius * 2 + 1
    try:
        image = pyautogui.screenshot(region=(left, top, size, size))
    except Exception:
        return False
    try:
        for px in range(size):
            for py in range(size):
                r, g, b = image.getpixel((px, py))[:3]
                if predicate((int(r), int(g), int(b))):
                    return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------


class Runtime:
    """Thread-safe status flags and simple session statistics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._status = "pause"
        self._stop = Event()
        self.skips = 0
        self.breaks = 0
        self.fatigue_pauses = 0
        self.started_at = time.perf_counter()
        self.active_seconds = 0.0
        self._active_since: float | None = None

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def set_status(self, status: str) -> bool:
        """Set status; returns True when it actually changed."""
        with self._lock:
            if self._status == status:
                return False
            self._status = status
            now = time.perf_counter()
            if status == "run" and self._active_since is None:
                self._active_since = now
            elif status != "run" and self._active_since is not None:
                self.active_seconds += now - self._active_since
                self._active_since = None
            return True

    def toggle(self) -> str:
        return "pause" if self.status == "run" else "run"

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep that wakes early when a stop is requested."""
        return self._stop.wait(seconds)

    def register_skip(self) -> None:
        with self._lock:
            self.skips += 1

    def register_break(self) -> None:
        with self._lock:
            self.breaks += 1

    def register_fatigue(self) -> None:
        with self._lock:
            self.fatigue_pauses += 1

    def elapsed(self) -> float:
        with self._lock:
            return time.perf_counter() - self.started_at

    def active_time(self) -> float:
        with self._lock:
            active = self.active_seconds
            if self._active_since is not None:
                active += time.perf_counter() - self._active_since
            return active


class Logger:
    """Console logger with optional file mirroring."""

    def __init__(self, to_file: bool) -> None:
        self._lock = Lock()
        self._file = None
        if to_file:
            try:
                self._file = open(LOG_PATH, "a", encoding="utf-8")  # noqa: SIM115
            except Exception:
                self._file = None

    def log(self, message: str) -> None:
        with self._lock:
            stamp = time.strftime("%H:%M:%S")
            line = f"[{stamp}] {message}"
            print(line)
            if self._file is not None:
                try:
                    self._file.write(line + "\n")
                    self._file.flush()
                except Exception:
                    pass

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class Detector:
    """Pixel-based dialogue state detection."""

    AUTOPLAY_COLOR = (236, 229, 216)
    WHITE = (255, 255, 255)

    def __init__(self, config: Config, layout: ScreenLayout) -> None:
        self.config = config
        self.layout = layout
        self.points = layout.points(config.device)

    def _point(self, name: str) -> tuple[int, int]:
        if name not in self.points:
            raise KeyError(name)
        return self.points[name]

    def is_loading(self) -> bool:
        """True while the mostly-white loading screen is visible."""
        x, y = self._point("LOADING_SCREEN_Y")
        return is_whiteish(get_pixel(x, y), 250)

    def is_dialogue_playing(self) -> bool:
        """True when the autoplay/continue indicator is on screen."""
        x, y = self._point("PLAYING_ICON_Y")
        return region_has_color(
            x,
            y,
            self.config.pixel_radius,
            lambda rgb: color_close(
                rgb, self.AUTOPLAY_COLOR, self.config.color_tolerance
            ),
        )

    def is_dialogue_option_available(self) -> bool:
        """True when a dialogue choice is available."""
        if self.is_loading():
            return False
        x, _ = self._point("DIALOGUE_ICON_LOWER_Y")
        for name in ("DIALOGUE_ICON_LOWER_Y", "DIALOGUE_ICON_HIGHER_Y"):
            _, y = self._point(name)
            if region_has_color(x, y, self.config.pixel_radius, is_whiteish):
                return True
        return False

    def dialogue_active(self) -> bool:
        """True when dialogue is playing or dialogue options are visible."""
        return self.is_dialogue_playing() or self.is_dialogue_option_available()

    def describe(self) -> str:
        """Human-readable snapshot used by --probe and --debug."""
        title = get_foreground_title()
        lines = [
            f"Resolution : {self.config.width}x{self.config.height}",
            f"Foreground : {title or '<unknown>'}",
            f"Device     : {self.config.device}",
            f"Detected   : {'LOADING' if self.is_loading() else 'gameplay'}",
        ]
        for name, (x, y) in sorted(self.points.items()):
            rgb = get_pixel(x, y)
            rgb_text = (
                f"({rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d})" if rgb else "<read failed>"
            )
            lines.append(f"  {name:<26} {x:>5},{y:<5} {rgb_text}")
        lines.append(f"Dialogue playing : {self.is_dialogue_playing()}")
        lines.append(f"Options available: {self.is_dialogue_option_available()}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def next_delay(config: Config, rng: Random) -> float:
    """Human-like delay between key presses (default around 1 second)."""
    if not config.humanize or config.interval_jitter <= 0:
        return config.skip_interval
    delay = config.skip_interval + rng.uniform(
        -config.interval_jitter, config.interval_jitter
    )
    return max(config.min_interval, delay)


def run_loop(
    config: Config,
    detector: Detector,
    runtime: Runtime,
    logger: Logger,
    rng: Random,
    debug: bool = False,
) -> None:
    """Detection / key-press loop, runs in a background thread."""
    next_press_at = time.perf_counter() + config.skip_interval
    next_break_check = time.perf_counter() + 30.0
    fatigue_threshold = rng.randint(config.fatigue_min, config.fatigue_max)
    streak = 0
    debug_at = 0.0
    session_limit = config.max_session_minutes * 60.0

    while not runtime.stopping:
        if runtime.status != "run":
            runtime.wait(0.25)
            next_press_at = time.perf_counter() + config.skip_interval
            continue

        if session_limit and runtime.active_time() >= session_limit:
            logger.log(
                f"  Session limit of {config.max_session_minutes:g} min reached. "
                "Pausing to be safe."
            )
            runtime.set_status("pause")
            continue

        now = time.perf_counter()

        if not is_game_active(config):
            if debug and now >= debug_at:
                logger.log(f"  Waiting for '{config.window_title}' to be focused...")
                debug_at = now + 3.0
            runtime.wait(0.4)
            next_press_at = time.perf_counter() + config.skip_interval
            continue

        if debug and now >= debug_at:
            logger.log(detector.describe())
            debug_at = now + 2.0

        active = detector.dialogue_active()
        if not active:
            runtime.wait(config.poll_interval)
            continue

        # Occasional break to avoid non-stop input.
        if config.breaks_enabled and now >= next_break_check:
            next_break_check = now + 30.0
            if rng.random() < config.break_chance:
                duration = rng.uniform(config.break_min, config.break_max)
                runtime.register_break()
                logger.log(f"  Taking a {duration:.1f}s break...")
                runtime.wait(duration)
                next_press_at = time.perf_counter() + config.skip_interval
                continue

        # "Reading" pause after a long streak of skips.
        if config.humanize and streak >= fatigue_threshold:
            duration = rng.uniform(config.fatigue_pause_min, config.fatigue_pause_max)
            runtime.register_fatigue()
            logger.log(f"  Short human-like pause ({duration:.1f}s)...")
            runtime.wait(duration)
            streak = 0
            fatigue_threshold = rng.randint(config.fatigue_min, config.fatigue_max)
            next_press_at = time.perf_counter() + config.skip_interval
            continue

        if now < next_press_at:
            runtime.wait(min(config.poll_interval, next_press_at - now))
            continue

        try:
            # A quick double-press is *not* used: one press per interval is
            # both gentler on the game and much less suspicious than spam.
            pyautogui.press(config.confirm_button)
            runtime.register_skip()
            streak += 1
        except Exception as exc:
            logger.log(f"  [error] Could not press '{config.confirm_button}': {exc}")

        next_press_at = time.perf_counter() + next_delay(config, rng)
        # Small nap after a press keeps CPU usage low.
        runtime.wait(min(config.poll_interval, 0.05))


# ---------------------------------------------------------------------------
# Hotkey listener
# ---------------------------------------------------------------------------


def build_hotkey_watcher(
    config: Config, runtime: Runtime, logger: Logger
) -> HotkeyWatcher:
    """Wire the configured hotkeys to runtime actions."""

    def start() -> None:
        if runtime.set_status("run"):
            logger.log("  STATUS: RUNNING - auto-skip is active")

    def pause() -> None:
        if runtime.set_status("pause"):
            logger.log("  STATUS: PAUSED - auto-skip is inactive")

    def toggle() -> None:
        new_status = runtime.toggle()
        runtime.set_status(new_status)
        logger.log(f"  STATUS: {new_status.upper()}")

    def quit_program() -> None:
        logger.log("  Shutting down... bye!")
        runtime.stop()

    return HotkeyWatcher(
        {
            config.start_vk: start,
            config.pause_vk: pause,
            config.toggle_vk: toggle,
            config.exit_vk: quit_program,
        }
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_seconds(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def print_stats(runtime: Runtime) -> None:
    print()
    print("=" * 60)
    print("  SESSION SUMMARY")
    print("=" * 60)
    print(f"  Runtime        : {_format_seconds(runtime.elapsed())}")
    print(f"  Active time    : {_format_seconds(runtime.active_time())}")
    print(f"  Keys pressed   : {runtime.skips}")
    print(f"  Breaks         : {runtime.breaks}")
    print(f"  Human pauses   : {runtime.fatigue_pauses}")
    print("=" * 60)


def print_banner(config: Config) -> None:
    print()
    print("=" * 62)
    print("  GENSHIN IMPACT - DIALOGUE AUTO-SKIP")
    print(f"  Version {VERSION} | Keyboard & Mouse Edition")
    print("=" * 62)
    print(f"  Resolution : {config.width}x{config.height} (auto-detected)")
    print(f"  Interact   : [{config.confirm_button.upper()}]")
    print(
        f"  Skip delay : {config.skip_interval:g}s (jitter +/-{config.interval_jitter:g}s)"
    )
    print(f"  Device     : {config.device}")
    print(f"  Focus lock : {'on' if config.require_focus else 'off'}")
    print(f"  Human mode : {'on' if config.humanize else 'off'}")
    print("-" * 62)
    print("  Controls:")
    print(f"    [{vk_name(config.start_vk):>4}]  Start")
    print(f"    [{vk_name(config.pause_vk):>4}]  Pause")
    print(f"    [{vk_name(config.toggle_vk):>4}]  Toggle start/pause")
    print(f"    [{vk_name(config.exit_vk):>4}]  Quit")
    print("=" * 62)
    print("  Hotkeys are read directly from Windows key state, so they")
    print("  work even when global keyboard hooks are blocked by a game.")
    print("  If they still do not respond, try 'Run as administrator'.")
    print("=" * 62)
    print()


def check_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genshin Impact dialogue auto-skipper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="seconds between key presses (default 1.0)",
    )
    parser.add_argument(
        "--autostart", action="store_true", help="start skipping without pressing F8"
    )
    parser.add_argument(
        "--no-focus-check",
        action="store_true",
        help="act even when the game window is not focused (not recommended)",
    )
    parser.add_argument(
        "--no-humanize", action="store_true", help="disable random timing/pauses"
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="print resolution, window, and detection pixel colors, then exit",
    )
    parser.add_argument(
        "--hotkey-test",
        action="store_true",
        help="verify that the start/pause/quit keys are detected, then exit",
    )
    parser.add_argument(
        "--press-test",
        action="store_true",
        help="send the interact key once after a 5 second countdown, then exit",
    )
    parser.add_argument(
        "--debug", action="store_true", help="print detection details while running"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="do not write detected values to .env"
    )
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="ignore saved settings and rewrite .env with auto-detected values",
    )
    parser.add_argument(
        "--session-minutes",
        type=float,
        default=None,
        help="auto-pause after this many active minutes (0 = unlimited)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if args.reset_config and ENV_PATH.exists():
        ENV_PATH.unlink()
        for key in list(os.environ):
            if key in {
                "WIDTH",
                "HEIGHT",
                "CONFIRM_BUTTON",
                "DEVICE",
                "SKIP_INTERVAL",
                "INTERVAL_JITTER",
                "MIN_INTERVAL",
            }:
                os.environ.pop(key, None)

    config = load_config(no_save=args.no_save)
    if args.interval is not None:
        config.skip_interval = max(0.2, args.interval)
        config.min_interval = min(config.min_interval, config.skip_interval)
        config.interval_jitter = min(config.interval_jitter, config.skip_interval / 4)
    if args.autostart:
        config.autostart = True
    if args.no_focus_check:
        config.require_focus = False
    if args.no_humanize:
        config.humanize = False
    if args.session_minutes is not None:
        config.max_session_minutes = max(0.0, args.session_minutes)

    try:
        layout = ScreenLayout(config.width, config.height)
    except ValueError as exc:
        print(f"  [error] {exc}")
        return 2

    try:
        detector = Detector(config, layout)
    except (ValueError, KeyError) as exc:
        print(f"  [error] {exc}")
        return 2

    if args.press_test:
        print_banner(config)
        print("  KEY PRESS TEST")
        print(
            f"  Focus the game window. Sending '{config.confirm_button}' in 5 seconds..."
        )
        print("  (This only tests key injection; it does not check dialogue.)")
        for remaining in range(5, 0, -1):
            print(f"    {remaining}...", end="", flush=True)
            time.sleep(1.0)
        print()
        try:
            pyautogui.press(config.confirm_button)
            print("  Key sent.")
            print("  If the game did not react, run this launcher as Administrator.")
        except Exception as exc:
            print(f"  [error] Could not send key: {exc}")
        return 0

    if args.hotkey_test:
        print_banner(config)
        print("  HOTKEY TEST")
        print("  Press each control key now. Press the quit key (or Esc) to finish.")
        print(
            f"  Start={vk_name(config.start_vk)}  Pause={vk_name(config.pause_vk)}  "
            f"Toggle={vk_name(config.toggle_vk)}  Quit={vk_name(config.exit_vk)}"
        )
        print()
        finished = Event()

        def report(label: str) -> None:
            print(f"  [detected] {label}", flush=True)

        def finish() -> None:
            report("QUIT")
            finished.set()

        watcher = HotkeyWatcher(
            {
                config.start_vk: lambda: report("START"),
                config.pause_vk: lambda: report("PAUSE"),
                config.toggle_vk: lambda: report("TOGGLE"),
                config.exit_vk: finish,
                0x1B: finish,  # Esc
            },
            interval=0.02,
        )
        watcher.start()
        try:
            finished.wait(timeout=30.0)
        finally:
            watcher.stop()
        print()
        print("  If nothing was detected, run this terminal as Administrator.")
        return 0

    if args.probe:
        print_banner(config)
        print(detector.describe())
        print()
        print("  Tip: the game must be showing a dialogue for the 'playing'")
        print("       / 'options' lines above to be True.")
        return 0

    logger = Logger(config.log_to_file)
    runtime = Runtime()

    print_banner(config)
    if not check_admin():
        print("  [warn] Not running as Administrator. If hotkeys or key")
        print("         presses do nothing while the game is focused, restart")
        print("         with 'Run as administrator'.")
        print()

    if config.autostart:
        runtime.set_status("run")
        logger.log("  Autostart enabled - skipping immediately.")
    else:
        logger.log(f"  Waiting for input... press {vk_name(config.start_vk)} to start.")

    worker = Thread(
        target=run_loop,
        args=(config, detector, runtime, logger, Random()),
        kwargs={"debug": args.debug},
        name="autoskip-loop",
        daemon=True,
    )

    listener = build_hotkey_watcher(config, runtime, logger)
    worker.start()
    listener.start()

    try:
        while worker.is_alive() and not runtime.stopping:
            time.sleep(0.2)
    except KeyboardInterrupt:
        logger.log("  Interrupted by user.")
        runtime.stop()
    finally:
        runtime.stop()
        try:
            listener.stop()
        except Exception:
            pass
        worker.join(timeout=2.0)
        logger.close()

    print_stats(runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
