#!/usr/bin/env python3
"""Test: drive the Windows Snipping Tool to capture the screen and save it.

Flow:
  1. Win+Shift+S  -> opens the Windows snip overlay (rectangular mode).
  2. Drag corner-to-corner -> selects (almost) the whole screen. The snip
     lands on the CLIPBOARD, not a file (that's how Win+Shift+S works).
  3. Read the clipboard image with Pillow and save it to a PNG file.

This proves the automation can drive a real Windows tool end to end.

Run:
    .venv\\Scripts\\python.exe automation\\snip_test.py
    .venv\\Scripts\\python.exe automation\\snip_test.py --out C:\\path\\to\\out.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    import pyautogui
except ImportError as e:  # pragma: no cover - optional extra
    raise SystemExit(
        "pyautogui fehlt. Installieren:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt"
    ) from e

# Pillow ships with the main pipeline, so it's already in the venv. ImageGrab
# is Windows/macOS only — exactly where this script is meant to run.
try:
    from PIL import ImageGrab
except ImportError as e:  # pragma: no cover - optional extra
    raise SystemExit("Pillow fehlt (sollte in der venv sein).") from e

SHOTS_DIR = Path(__file__).resolve().parent / "shots"

# Failsafe stays ON (mouse to a corner aborts), but we deliberately avoid the
# exact (0,0) corner during the drag — start a few px in so we don't trip it.
pyautogui.FAILSAFE = True
MARGIN = 8


def snip_fullscreen(out: Path) -> Path:
    if sys.platform != "win32":
        raise SystemExit(
            "Dieser Test ist für Windows (Snipping Tool). "
            "Auf einem anderen OS bitte desktop.shot() nutzen."
        )

    w, h = pyautogui.size()

    print("Öffne Snip-Overlay (Win+Shift+S) …")
    pyautogui.hotkey("win", "shift", "s")
    # Give the overlay time to fade in before we start dragging.
    time.sleep(1.5)

    print("Ziehe über den ganzen Bildschirm …")
    pyautogui.moveTo(MARGIN, MARGIN, duration=0.2)
    # mouseDown/Up is more reliable for the snip overlay than dragTo().
    pyautogui.mouseDown(button="left")
    pyautogui.moveTo(w - MARGIN, h - MARGIN, duration=0.6)
    pyautogui.mouseUp(button="left")

    # The snip is copied to the clipboard asynchronously — give Windows a beat.
    time.sleep(1.2)

    img = ImageGrab.grabclipboard()
    if img is None:
        raise SystemExit(
            "Zwischenablage enthält kein Bild. Mögliche Gründe: Overlay kam zu "
            "spät, oder der Snip wurde abgebrochen. Nochmal versuchen — evtl. "
            "die time.sleep-Werte oben erhöhen."
        )

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Snipping-Tool screenshot test")
    ap.add_argument("--out", type=Path,
                    default=SHOTS_DIR / "snip_test.png",
                    help="Zielpfad für das PNG (Default: automation/shots/snip_test.png)")
    args = ap.parse_args()

    print("Start in 3 s — wechsle ggf. zum Chat-Fenster. "
          "Not-Aus: Maus in die obere linke Ecke.")
    time.sleep(3)

    path = snip_fullscreen(args.out)
    print(f"OK — gespeichert: {path}")
