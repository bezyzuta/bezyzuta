#!/usr/bin/env python3
"""Browser automation via Playwright — drives a real Chromium over the DOM.

Use this for web apps (YouTube/TikTok upload, Higgsfield/Grok web, any login
flow). Unlike pixel-based tools it clicks elements by selector, so it survives
window moves and resolution changes.

Key idea: a PERSISTENT profile. The first run you log in by hand once; the
session cookies live in `automation/.browser_profile/` and every later run is
already logged in — no password automation, no 2FA headaches.

Install:
    .venv\\Scripts\\python.exe -m pip install -r automation\\requirements-automation.txt
    .venv\\Scripts\\python.exe -m playwright install chromium

Quick smoke test (opens a visible browser, screenshots example.com):
    .venv\\Scripts\\python.exe automation\\browser.py
"""

from __future__ import annotations

import time
from pathlib import Path

# Playwright is an optional extra (see requirements-automation.txt). Fail with
# an actionable message instead of a bare ImportError if it isn't installed.
try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError as e:  # pragma: no cover - depends on optional extra
    raise SystemExit(
        "Playwright is not installed. Run:\n"
        "  .venv\\Scripts\\python.exe -m pip install -r "
        "automation\\requirements-automation.txt\n"
        "  .venv\\Scripts\\python.exe -m playwright install chromium"
    ) from e


# Where the persistent login profile lives. Committed-out via .gitignore so
# your cookies never end up in git.
PROFILE_DIR = Path(__file__).resolve().parent / ".browser_profile"
# Where smoke-test / debug screenshots land.
SHOTS_DIR = Path(__file__).resolve().parent / "shots"


class Browser:
    """Thin, ergonomic wrapper around a persistent Playwright Chromium.

    Use as a context manager so the browser always closes cleanly:

        with Browser(headless=False) as b:
            b.goto("https://studio.youtube.com")
            b.click("text=Erstellen")
            b.upload("input[type=file]", r"C:\\path\\to\\short.mp4")
            b.shot("after_upload")
    """

    def __init__(self, headless: bool = False, slow_mo_ms: int = 0,
                 profile_dir: Path = PROFILE_DIR):
        self.headless = headless
        # slow_mo adds a delay before each action — invaluable while you're
        # developing a flow and want to watch what it does.
        self.slow_mo_ms = slow_mo_ms
        self.profile_dir = Path(profile_dir)
        self._pw = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "Browser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        # launch_persistent_context keeps cookies/localStorage between runs —
        # this is what makes "log in once" work.
        self.ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            slow_mo=self.slow_mo_ms,
            viewport={"width": 1440, "height": 900},
            args=["--start-maximized"],
        )
        # Reuse the tab Chromium opens with, or make one.
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ── Navigation ────────────────────────────────────────────────────────
    def goto(self, url: str, wait: str = "load") -> None:
        """Open a URL. `wait` is Playwright's wait_until state."""
        assert self.page is not None
        self.page.goto(url, wait_until=wait, timeout=60_000)

    # ── Actions (all wait for the element first, so they're robust) ────────
    def click(self, selector: str, timeout_s: float = 15) -> None:
        assert self.page is not None
        self.page.click(selector, timeout=int(timeout_s * 1000))

    def fill(self, selector: str, text: str, timeout_s: float = 15) -> None:
        """Clear and type into an input/textarea."""
        assert self.page is not None
        self.page.fill(selector, text, timeout=int(timeout_s * 1000))

    def type_text(self, selector: str, text: str, delay_ms: int = 30) -> None:
        """Type key-by-key (for contenteditable / fields that need keystrokes)."""
        assert self.page is not None
        self.page.click(selector)
        self.page.type(selector, text, delay=delay_ms)

    def upload(self, selector: str, *file_paths: str) -> None:
        """Set files on an <input type=file>. Pass one or more absolute paths."""
        assert self.page is not None
        self.page.set_input_files(selector, list(file_paths))

    def wait_for(self, selector: str, timeout_s: float = 30) -> None:
        """Block until an element appears (e.g. an 'upload complete' marker)."""
        assert self.page is not None
        self.page.wait_for_selector(selector, timeout=int(timeout_s * 1000))

    def shot(self, name: str = "screenshot") -> Path:
        """Save a full-page screenshot to automation/shots/<name>.png."""
        assert self.page is not None
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOTS_DIR / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def pause(self) -> None:
        """Open Playwright Inspector — step through and PICK selectors live.

        This is the single most useful tool for building a flow: call
        b.pause() and use the inspector's 'Pick locator' to get the exact
        selector for any element on the page.
        """
        assert self.page is not None
        self.page.pause()


def _login_once(start_url: str) -> None:
    """Open a visible browser at `start_url`, let you log in, then save state.

    Run this once per site. After you've logged in (and solved any 2FA),
    press Enter in the terminal — the cookies are already persisted in the
    profile dir, so every later headless run is authenticated.
    """
    with Browser(headless=False) as b:
        b.goto(start_url)
        print(f"Logge dich im Browser bei {start_url} ein.")
        input("Wenn du eingeloggt bist, hier ENTER drücken … ")
        print(f"Session gespeichert in {PROFILE_DIR}")


def _smoke_test() -> None:
    """Prove the install works: open example.com and screenshot it."""
    with Browser(headless=False, slow_mo_ms=300) as b:
        b.goto("https://example.com")
        time.sleep(1)
        path = b.shot("smoke_example")
        print(f"OK — screenshot: {path}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Playwright browser automation")
    ap.add_argument("--login", metavar="URL",
                    help="Open a visible browser at URL to log in once.")
    args = ap.parse_args()
    if args.login:
        _login_once(args.login)
    else:
        _smoke_test()
