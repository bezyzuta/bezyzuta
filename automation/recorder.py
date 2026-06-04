#!/usr/bin/env python3
"""Record real mouse/keyboard events to JSON, then replay them.

This is the "just record what I do and play it back" option — no selectors,
no coordinates by hand. It captures absolute mouse moves/clicks/scrolls and
key presses with their timing, so replay reproduces the same actions at the
same pace.

Caveat: like all coordinate-based automation, a recording only replays
correctly if windows are in the same place and the resolution is unchanged.
For anything web-based, browser.py is far more reliable.

Record (press ESC to stop):
    .venv\\Scripts\\python.exe automation\\recorder.py record my_macro

Replay:
    .venv\\Scripts\\python.exe automation\\recorder.py play my_macro
    .venv\\Scripts\\python.exe automation\\recorder.py play my_macro --speed 2.0
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    from pynput import mouse, keyboard
except ImportError as e:  # pragma: no cover - depends on optional extra
    raise SystemExit(
        "pynput is not installed. Run:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt"
    ) from e

try:
    import pyautogui
except ImportError as e:  # pragma: no cover - depends on optional extra
    raise SystemExit(
        "pyautogui is not installed (needed for replay). Run:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt"
    ) from e

pyautogui.FAILSAFE = True

MACROS_DIR = Path(__file__).resolve().parent / "macros"


def _macro_path(name: str) -> Path:
    MACROS_DIR.mkdir(parents=True, exist_ok=True)
    return MACROS_DIR / (name if name.endswith(".json") else f"{name}.json")


def record(name: str) -> None:
    """Capture events until ESC is pressed, then save to macros/<name>.json."""
    events: list[dict] = []
    start = time.time()

    def t() -> float:
        return round(time.time() - start, 4)

    def on_move(x, y):
        events.append({"t": t(), "type": "move", "x": x, "y": y})

    def on_click(x, y, button, pressed):
        events.append({"t": t(), "type": "click", "x": x, "y": y,
                       "button": button.name, "pressed": pressed})

    def on_scroll(x, y, dx, dy):
        events.append({"t": t(), "type": "scroll", "x": x, "y": y,
                       "dx": dx, "dy": dy})

    def on_press(key):
        if key == keyboard.Key.esc:
            return False  # stop the keyboard listener
        events.append({"t": t(), "type": "key", "key": _key_name(key)})

    print("Aufnahme läuft … ESC drückt = Stop.")
    m_listener = mouse.Listener(on_move=on_move, on_click=on_click,
                                on_scroll=on_scroll)
    m_listener.start()
    with keyboard.Listener(on_press=on_press) as k_listener:
        k_listener.join()
    m_listener.stop()

    path = _macro_path(name)
    path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"{len(events)} Events gespeichert → {path}")


def _key_name(key) -> str:
    """Serialize a pynput key to a string pyautogui understands."""
    try:
        return key.char  # printable character
    except AttributeError:
        return key.name  # special key like 'enter', 'shift', 'space'


def play(name: str, speed: float = 1.0) -> None:
    """Replay a recorded macro. `speed` >1 is faster, <1 slower."""
    path = _macro_path(name)
    if not path.exists():
        raise SystemExit(f"Kein Macro: {path}")
    events = json.loads(path.read_text(encoding="utf-8"))
    if not events:
        print("Macro ist leer.")
        return

    print(f"Replay {path.name} ({len(events)} events, speed {speed}x). "
          "Maus in obere linke Ecke = Abbruch.")
    last_t = 0.0
    for ev in events:
        # Sleep the real inter-event gap (scaled by speed) so timing matches.
        gap = (ev["t"] - last_t) / max(speed, 0.01)
        if gap > 0:
            time.sleep(gap)
        last_t = ev["t"]

        kind = ev["type"]
        if kind == "move":
            pyautogui.moveTo(ev["x"], ev["y"])
        elif kind == "click":
            if ev["pressed"]:
                pyautogui.mouseDown(ev["x"], ev["y"], button=ev["button"])
            else:
                pyautogui.mouseUp(ev["x"], ev["y"], button=ev["button"])
        elif kind == "scroll":
            pyautogui.scroll(int(ev["dy"]) * 100, x=ev["x"], y=ev["y"])
        elif kind == "key":
            key = ev["key"]
            if key and len(key) == 1:
                pyautogui.press(key)
            elif key:
                pyautogui.press(key)
    print("Fertig.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Record/replay mouse+keyboard macros")
    ap.add_argument("mode", choices=["record", "play"])
    ap.add_argument("name", help="macro name (stored under automation/macros/)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="replay speed multiplier (play only)")
    args = ap.parse_args()

    if args.mode == "record":
        record(args.name)
    else:
        play(args.name, speed=args.speed)
