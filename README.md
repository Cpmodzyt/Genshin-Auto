# Genshin Auto — Dialogue Auto-Skip

> **⚠️ DISCLAIMER — READ THIS FIRST**
>
> Automating Genshin Impact violates the game's Terms of Service and can get
> your account permanently banned. This project is shared for educational
> purposes only. **You use it at your own risk.**
>
> The "human-like" timings in this project make the input pattern less
> robotic, but they **do not hide the program from anti-cheat** and they do
> **not** make automation safe. No automation tool can guarantee that your
> account will not be actioned.

A Windows dialogue auto-skipper for Genshin Impact. It watches a few screen
pixels to detect dialogue, then presses your in-game interact key on a
natural ~1 second interval. It only acts while the game is focused.

---

## ✨ What's new in v2.0

| Fix / feature | Why it matters |
|---|---|
| **Auto resolution detection** | On every launch the screen size is re-read and `.env` is repaired automatically. A stale resolution from another PC was the #1 cause of "F8 does nothing". |
| **DPI-aware coordinates** | Works correctly on 125 % / 150 % Windows display scaling. |
| **Hook-free hotkeys** | Hotkeys are read with `GetAsyncKeyState` instead of a global keyboard hook. Genshin's anti-cheat commonly blocks hooks, which made F8/F9 silently stop working. |
| **1 second default** | Default delay is now **1.0 s** (configurable), with a little natural jitter — no more press-spam. |
| **Auto-elevation** | `run.bat` relaunches itself as Administrator so key presses are not ignored. |
| **Self-checking launcher** | Checks Python 3.11+, reuses the venv, installs only missing dependencies, verifies imports and config, then starts. |
| **Diagnostics** | `--probe` and `--hotkey-test` tell you exactly what is wrong in seconds. |
| **Human-like mode** | Randomized intervals, occasional breaks, and "reading" pauses after long skip streaks. |
| **Session limit** | Optional auto-pause after N active minutes. |
| **Logging + stats** | Optional `autoskip.log` and an end-of-session summary. |
| **Tests** | 18 unit tests for coordinates, colours, hotkeys, config and timing. |

---

## 📋 Table of Contents

- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Controls](#-controls)
- [Diagnostics](#-diagnostics)
- [Configuration](#-configuration)
- [How It Works](#-how-it-works)
- [Troubleshooting](#-troubleshooting)
- [About "anti-detection"](#-about-anti-detection)
- [Development](#-development)
- [License](#-license)

---

## 🎮 Features

- **Dialogue detection** using calibrated pixel checks.
- **Automatic option handling** — presses your interaction key when dialogue
  choices appear.
- **Auto resolution / multi-resolution support** — 16:9, 2K, 4K, ultrawide
  and a special 2880×1800 profile.
- **DPI scaling aware** — coordinates match what is actually on screen.
- **Focus lock** — only acts while `Genshin Impact` is the foreground window.
- **Loading-screen guard** — does not press keys on the white loading screen.
- **Human-like behaviour** (optional):
  - delay of 1.0 s ± 0.2 s between presses,
  - 4 % chance of a 3–8 s break every 30 s,
  - a 1.5–4 s "reading" pause after 10–22 consecutive skips.
- **Hook-free global hotkeys** — F8 / F9 / F7 / F12 by default, all
  configurable.
- **Autostart mode** — start skipping immediately without a hotkey.
- **Safe session limit** — auto-pause after a configurable number of minutes.
- **Probe / debug / hotkey-test modes** for fast troubleshooting.
- **Lightweight** — no reading of game memory, no injection, no DLLs, no
  network calls.

---

## 📦 Requirements

- **OS:** Windows 10 / 11
- **Python:** 3.11 or newer (3.12/3.13 recommended)
- **Privileges:** Administrator recommended (required for reliable key input)
- **Game setting:** **Settings → Other → Auto-Play Story = Off**
- The game must be on the **primary monitor** (multi-monitor capture is not
  supported by this version).

---

## 🚀 Installation

### Option 1 — `run.bat` (recommended)

1. Clone the repository:
   ```bat
   git clone https://github.com/Cpmodzyt/Genshin-Auto.git
   cd Genshin-Auto
   ```
   (Or download the ZIP from the GitHub page.)
2. Right-click **`run.bat` → Run as administrator**.
   - If you forget, it will ask Windows for elevation itself.
   - It verifies Python 3.11+, creates `.venv`, installs only the missing
     dependencies, re-checks that they import, validates the config, and only
     then starts the app.
3. On first run it records your screen size in `.env`.

You can also pass options through the launcher:

```bat
run.bat --probe
run.bat --hotkey-test
run.bat --debug
```

### Option 2 — manual

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe autoskip_dialogue.py
```

Or with [uv](https://github.com/astral-sh/uv):

```bat
uv sync
uv run autoskip_dialogue.py
```

---

## 📖 Quick Start

1. Launch Genshin Impact and make sure it is on the primary screen.
2. Start `run.bat` as Administrator.
3. Optionally run a sanity check first:
   ```bat
   run.bat --probe
   ```
   You should see your real resolution (for example `1920x1080`), the
   foreground window, and the RGB value of each detection pixel.
4. Go back to the game and press **F8**.
5. Continue playing. Dialogue is advanced automatically while the game is
   focused.
6. Press **F9** to pause, **F7** to toggle, **F12** to quit.

> The console shows `STATUS: RUNNING` when F8 is received. If that line never
> appears, run `run.bat --hotkey-test` and follow the
> [troubleshooting](#-troubleshooting) section.

---

## 🎛 Controls

| Default key | Action | `.env` variable |
|---|---|---|
| **F8** | Start auto-skip | `START_KEY` |
| **F9** | Pause auto-skip | `PAUSE_KEY` |
| **F7** | Toggle start/pause | `TOGGLE_KEY` |
| **F12** | Quit program | `EXIT_KEY` |

Hotkeys are read directly from Windows key state, so they work even while the
game has focus and even when global keyboard hooks are blocked.

---

## 🩺 Diagnostics

These modes are the fastest way to find out why nothing happens.

### `--probe`

Prints one snapshot and exits:

```bat
run.bat --probe
```

Output includes:

```
Resolution : 1920x1080
Foreground : Genshin Impact
Device     : mnk
Detected   : gameplay
  DIALOGUE_ICON_HIGHER_Y      1301,790   ( 24,  33,  98)
  DIALOGUE_ICON_LOWER_Y       1301,808   ( 21,  29,  92)
  LOADING_SCREEN_Y            1200,700   ( 18,  22,  83)
  PLAYING_ICON_Y                84,46    ( 29,  34,  47)
Dialogue playing : False
Options available: False
```

Start a dialogue in the game while it runs and the last two lines should
become `True`. If they never do, see [Detection never triggers](#detection-never-triggers).

### `--hotkey-test`

```bat
run.bat --hotkey-test
```

Press F8 / F9 / F7 / F12 (or Esc to stop). Each detected key is printed. If
nothing is printed, run the terminal as Administrator.

### `--debug`

```bat
run.bat --debug
```

Continuously prints the same information every two seconds while the normal
auto-skip loop runs.

### `--autostart`

```bat
run.bat --autostart
```

Skips immediately; useful if hotkeys are blocked by another overlay.

---

## ⚙️ Configuration

Configuration lives in `.env` next to the script. It is created on the first
run and is **git-ignored** (it contains machine-specific values).

| Variable | Default | Meaning |
|---|---|---|
| `WIDTH`, `HEIGHT` | auto | Screen size. **Auto-repaired on every launch.** |
| `CONFIRM_BUTTON` | `f` | In-game interact/continue key. |
| `DEVICE` | `mnk` | `mnk` (mouse + keyboard). |
| `SKIP_INTERVAL` | `1.0` | Seconds between key presses. |
| `INTERVAL_JITTER` | `0.2` | Random ± seconds added to the interval. |
| `MIN_INTERVAL` | `0.85` | Hard lower bound for the interval. |
| `COLOR_TOLERANCE` | `16` | Per-channel tolerance for colour matching. |
| `PIXEL_RADIUS` | `1` | Small search radius around a detection pixel (0–4). |
| `REQUIRE_FOCUS` | `true` | Only act while the game is focused. |
| `WINDOW_TITLE` | `Genshin Impact` | Foreground title to match (substring). |
| `BREAKS_ENABLED` | `true` | Enable occasional breaks. |
| `BREAK_CHANCE` | `0.04` | Chance of a break per 30 s check. |
| `BREAK_MIN`, `BREAK_MAX` | `3.0`, `8.0` | Break duration range (seconds). |
| `HUMANIZE` | `true` | Enable jitter and "reading" pauses. |
| `START_KEY` | `f8` | Start hotkey (`f1`–`f24`, a letter, or `0x77`). |
| `PAUSE_KEY` | `f9` | Pause hotkey. |
| `TOGGLE_KEY` | `f7` | Toggle hotkey. |
| `EXIT_KEY` | `f12` | Quit hotkey. |
| `AUTOSTART` | `false` | Start without pressing the start key. |
| `MAX_SESSION_MINUTES` | `0.0` | Auto-pause after N active minutes; `0` = unlimited. |
| `LOG_TO_FILE` | `true` | Also write messages to `autoskip.log`. |

Command-line flags override the saved values for the current run:

```bat
run.bat --interval 1.0 --session-minutes 45 --no-humanize
run.bat --no-focus-check
run.bat --reset-config
```

> **Note:** the auto-detected `WIDTH`/`HEIGHT` always win. If you need a
> manual override for an unusual setup, use `--no-save` and edit `.env`
> afterwards, but normally you should not need to touch it.

### Supported resolutions

Tested geometry profiles:

- 1920×1080 (Full HD) and every 16:9 size (1280×720, 1600×900, 2560×1440,
  3840×2160 …) by proportional scaling,
- 2880×1800 (exact profile),
- ultrawide 21:9 (e.g. 3440×1440) via the `wide_screen` profile.

---

## 🔧 How It Works

1. At launch, DPI awareness is enabled and the primary screen size is read in
   physical pixels. If it differs from `.env`, `.env` is rewritten.
2. Detection points authored for 1920×1080 are scaled to the current screen.
3. Every loop:
   - verify the foreground window contains `Genshin Impact`;
   - read the loading-screen pixel (skip if white);
   - read the autoplay/continue pixel and the dialogue-option pixels;
   - if dialogue is active and the delay elapsed, send one interact key.
4. Random jitter, breaks and reading pauses are applied on top.
5. F8/F9/F7/F12 are polled from the Windows key state and never install a
   keyboard hook.

No game memory is read, no DLL is injected, and no network connection is
made.

---

## 🐛 Troubleshooting

### F8 does nothing / console never says RUNNING

1. Run the hotkey test:
   ```bat
   run.bat --hotkey-test
   ```
2. If no key is detected, start `run.bat` **as Administrator**. Overlays
   (Discord, GeForce Experience, MSI Afterburner) can also swallow keys —
   close them temporarily.
3. Some keyboards have a **Fn lock** where F8 is media-play. Hold `Fn` or
   switch the Fn lock, or change `START_KEY` to another key in `.env`.
4. As a fallback use `run.bat --autostart`.

### It runs but dialogue is never skipped

1. Run `run.bat --probe` while a dialogue is visible.
2. Confirm the printed resolution equals your Windows resolution.
3. Confirm `Dialogue playing` or `Options available` becomes `True`.
4. Confirm `Foreground` is `Genshin Impact` (not the launcher).
5. Ensure **Auto-Play Story** is **Off** in game settings.
6. Make sure the game is on the **primary monitor** and not borderless
   across multiple monitors.

### Detection never triggers

- Increase the tolerance in `.env`: `COLOR_TOLERANCE=24` (try up to 32).
- Or set `PIXEL_RADIUS=2`.
- Some UI themes/game versions shift the indicator. Use `--probe` and report
  the RGB values in an issue.
- If your resolution was changed after the last launch, no problem — v2
  re-detects it automatically every time.

### `run.bat` closes immediately

Run it from a terminal so you can read the error:

```bat
cmd /k run.bat
```

Common causes: Python not on `PATH`, no internet for the first dependency
install, or UAC declined.

### Key presses do nothing in game

- Run as Administrator.
- Use **borderless windowed** or **windowed** mode; some exclusive-fullscreen
  setups drop synthetic input.
- Verify the interact key in `.env` matches the in-game key.

### The game is laggy / presses feel too fast

Raise `SKIP_INTERVAL` to `1.5` or `2.0`, or keep the default `1.0`.

---

## 🥷 About "anti-detection"

A few honest points:

- This project **does not** bypass or disable anti-cheat, hide processes,
  spoof hardware, or alter game memory.
- `HUMANIZE=true` adds randomized timing, breaks and pauses. That is all it
  does.
- Anti-cheat systems can still detect automation through input patterns,
  process inspection, or server-side behaviour. **No setting here makes the
  tool safe.**
- The only reliable way to avoid a ban is to not automate the game.

Use it on an account you can afford to lose.

---

## 🤝 Development

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Optional checks:

```bat
uvx ruff check .
uvx ruff format .
```

Project layout:

```
autoskip_dialogue.py   main program
tests/test_core.py     unit tests (no game required)
run.bat                launcher (auto-elevates, sets up venv)
requirements.txt       runtime dependencies
.env                   generated per-machine config (git-ignored)
autoskip.log           optional runtime log (git-ignored)
```

Pull requests are welcome. Please keep changes typed and add tests for pure
logic (coordinates, colours, timing, config parsing).

---

## 📄 License

Provided as-is for educational purposes. See [LICENSE](LICENSE).

**Not affiliated with HoYoverse / miHoYo.** Genshin Impact is a trademark of
its respective owners.
