#!/usr/bin/env python3
"""Desktop automation via pyautogui — real OS-level mouse/keyboard + screen.

Use this for NATIVE apps that have no API and can't be driven by a browser.
It is pixel/image based, so it's inherently more fragile than browser.py:
if the window moves or the resolution changes, coordinates drift. Prefer
image-anchored clicks (`click_image`) over raw coordinates wherever you can.

SAFETY: pyautogui's failsafe is left ON. Slam the mouse into the TOP-LEFT
corner of the screen to abort a runaway script instantly (raises
FailSafeException).

Install:
    .venv\\Scripts\\python.exe -m pip install -r automation\\requirements-automation.txt

Quick demo (reports screen size + mouse position, takes a screenshot):
    .venv\\Scripts\\python.exe automation\\desktop.py
"""

from __future__ import annotations

import time
from pathlib import Path

try:
    import pyautogui
except ImportError as e:  # pragma: no cover - depends on optional extra
    raise SystemExit(
        "pyautogui is not installed. Run:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt"
    ) from e


# Move the mouse to a screen corner to kill a runaway script. Keep this ON.
pyautogui.FAILSAFE = True
# Small pause after every pyautogui call — gives slow apps time to react and
# makes runs visibly debuggable. Tune down once a flow is stable.
pyautogui.PAUSE = 0.25

SHOTS_DIR = Path(__file__).resolve().parent / "shots"
# Drop reference PNGs here (small crops of buttons/icons) for click_image().
ANCHORS_DIR = Path(__file__).resolve().parent / "anchors"


def screen_size() -> tuple[int, int]:
    return tuple(pyautogui.size())  # type: ignore[return-value]


def shot(name: str = "screen", region: tuple[int, int, int, int] | None = None) -> Path:
    """Screenshot the whole screen (or a region x,y,w,h) to automation/shots/."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOTS_DIR / f"{name}.png"
    pyautogui.screenshot(str(path), region=region)
    return path


def click_xy(x: int, y: int, clicks: int = 1, button: str = "left") -> None:
    """Click at absolute screen coordinates. Fragile — prefer click_image."""
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)


def move_to(x: int, y: int, duration_s: float = 0.3) -> None:
    pyautogui.moveTo(x, y, duration=duration_s)


def type_text(text: str, interval_s: float = 0.02) -> None:
    """Type a string into whatever currently has focus."""
    pyautogui.write(text, interval=interval_s)


def press(*keys: str) -> None:
    """Press one or more keys in sequence, e.g. press('enter')."""
    for k in keys:
        pyautogui.press(k)


def hotkey(*keys: str) -> None:
    """Press a key combo together, e.g. hotkey('ctrl', 's')."""
    pyautogui.hotkey(*keys)


def locate_image(name_or_path: str, confidence: float = 0.85):
    """Find an anchor image on screen, return its center Point or None.

    `name_or_path` is either a filename inside automation/anchors/ or an
    absolute path. `confidence` needs OpenCV (pulled in by pyautogui extras);
    lower it to ~0.7 if matches are flaky, raise it to avoid false hits.
    """
    path = Path(name_or_path)
    if not path.is_absolute():
        path = ANCHORS_DIR / name_or_path
    try:
        return pyautogui.locateCenterOnScreen(str(path), confidence=confidence)
    except pyautogui.ImageNotFoundException:
        return None


def click_image(name_or_path: str, confidence: float = 0.85,
                timeout_s: float = 10, clicks: int = 1) -> bool:
    """Wait for an anchor image to appear, then click its center.

    Returns True if it clicked, False if the image never showed up within
    `timeout_s`. This is the robust way to drive a native UI: capture a small
    crop of the button into automation/anchors/save_btn.png and call
    click_image('save_btn.png').
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pt = locate_image(name_or_path, confidence=confidence)
        if pt is not None:
            pyautogui.click(pt.x, pt.y, clicks=clicks)
            return True
        time.sleep(0.4)
    return False


def _demo() -> None:
    w, h = screen_size()
    x, y = pyautogui.position()
    print(f"Screen: {w}x{h}   Mouse jetzt bei: ({x}, {y})")
    print("Failsafe AN — Maus in die obere linke Ecke = sofortiger Abbruch.")
    path = shot("desktop_demo")
    print(f"Screenshot: {path}")


if __name__ == "__main__":
    _demo()
