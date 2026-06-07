#!/usr/bin/env python3
"""Attach to your ALREADY-OPEN Chrome and drive your real tabs/logins.

Unlike browser.py (which opens a clean, separate Chromium), this connects to
your normal Chrome over the DevTools Protocol (CDP). It sees the tabs you have
open, your cookies, your logged-in sessions — everything.

HOW IT WORKS (one-time setup):
  Chrome has to be started with a debug port. You can't attach to a Chrome that
  was launched normally. So:

  1. Close ALL Chrome windows (check the tray — Chrome must be fully gone).
  2. Start Chrome WITH the debug port, using your real profile:

       launch_chrome_debug()            # this script does it for you
     or manually:
       "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
         --remote-debugging-port=9222 ^
         --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\User Data"

  3. Your normal tabs/logins are there. Now attach() controls them.

Run the demo (launches debug Chrome if needed, lists your open tabs):
    .venv\\Scripts\\python.exe automation\\chrome_attach.py
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Browser as PWBrowser, Page
except ImportError as e:  # pragma: no cover - optional extra
    raise SystemExit(
        "Playwright fehlt. Installieren:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt\n"
        "  .venv\\Scripts\\python.exe -m playwright install chromium"
    ) from e

DEBUG_PORT = 9222

# Common Chrome install locations on Windows.
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def _find_chrome() -> str:
    for c in _CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit(
        "chrome.exe nicht gefunden. Pfad manuell in _CHROME_CANDIDATES eintragen."
    )


def launch_chrome_debug(use_real_profile: bool = True, port: int = DEBUG_PORT) -> None:
    """Start Chrome with the debug port so attach() can connect.

    use_real_profile=True uses your normal Chrome User Data (your tabs/logins).
    IMPORTANT: close all other Chrome windows first, or Chrome will just open a
    tab in the existing instance WITHOUT enabling the debug port.
    """
    chrome = _find_chrome()
    args = [chrome, f"--remote-debugging-port={port}"]
    if use_real_profile:
        user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        args.append(f"--user-data-dir={user_data}")
    # Detached so it keeps running after this script exits.
    subprocess.Popen(args, close_fds=True)
    print(f"Chrome mit Debug-Port {port} gestartet.")


class AttachedChrome:
    """Connect to a debug-port Chrome and drive its existing tabs.

        with AttachedChrome() as c:
            for p in c.pages():
                print(p.url)
            page = c.first_page()          # your active-ish tab
            page.goto("https://...")       # navigate it
            new = c.new_tab("https://...")  # or open a new tab
    """

    def __init__(self, port: int = DEBUG_PORT):
        self.port = port
        self._pw = None
        self.browser: PWBrowser | None = None

    def __enter__(self) -> "AttachedChrome":
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.connect_over_cdp(
                f"http://localhost:{self.port}"
            )
        except Exception as e:
            self._pw.stop()
            raise SystemExit(
                f"Konnte nicht an Chrome auf Port {self.port} andocken. "
                "Läuft Chrome MIT --remote-debugging-port? Erst alle Chrome-"
                "Fenster schließen, dann launch_chrome_debug() aufrufen."
            ) from e
        return self

    def __exit__(self, *exc) -> None:
        # NOTE: we do NOT close the browser — it's YOUR Chrome, leave it open.
        if self._pw:
            self._pw.stop()

    def pages(self) -> list[Page]:
        """All open tabs across all windows."""
        assert self.browser is not None
        out: list[Page] = []
        for ctx in self.browser.contexts:
            out.extend(ctx.pages)
        return out

    def first_page(self) -> Page:
        pages = self.pages()
        if not pages:
            raise SystemExit("Keine offenen Tabs gefunden.")
        return pages[0]

    def find_tab(self, url_contains: str) -> Page | None:
        """Find an open tab whose URL contains a substring (e.g. 'youtube')."""
        for p in self.pages():
            if url_contains.lower() in (p.url or "").lower():
                return p
        return None

    def new_tab(self, url: str | None = None) -> Page:
        assert self.browser is not None
        ctx = self.browser.contexts[0] if self.browser.contexts else None
        if ctx is None:
            raise SystemExit("Kein Browser-Context vorhanden.")
        page = ctx.new_page()
        if url:
            page.goto(url)
        return page


def _demo() -> None:
    # Try to attach; if nothing is listening on the port, offer to launch.
    try:
        with AttachedChrome() as c:
            tabs = c.pages()
            print(f"Angedockt — {len(tabs)} offene Tab(s):")
            for i, p in enumerate(tabs):
                print(f"  [{i}] {p.title()[:60]!r}  {p.url}")
    except SystemExit as e:
        print(e)
        ans = input("Debug-Chrome jetzt starten? (alle Chrome-Fenster werden "
                    "vorher von DIR geschlossen) [j/N] ")
        if ans.strip().lower() in ("j", "y"):
            launch_chrome_debug()
            print("Warte 3 s, dann nochmal versuchen …")
            time.sleep(3)
            with AttachedChrome() as c:
                tabs = c.pages()
                print(f"Angedockt — {len(tabs)} offene Tab(s):")
                for i, p in enumerate(tabs):
                    print(f"  [{i}] {p.title()[:60]!r}  {p.url}")


if __name__ == "__main__":
    _demo()
