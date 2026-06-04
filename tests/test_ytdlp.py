"""Tests for yt-dlp helpers: cookie args + actionable error hints.

Run: `pytest tests/test_ytdlp.py -v`
"""

import pipeline


class _Cfg:
    """Minimal stand-in; only the cookie fields matter here."""
    def __init__(self, browser="", file=""):
        self.youtube_cookies_from_browser = browser
        self.youtube_cookies_file = file


def test_cookie_args_empty_when_unset():
    assert pipeline.ytdlp_cookie_args(_Cfg()) == []
    assert pipeline.ytdlp_cookie_args(None) == []


def test_cookie_args_from_browser():
    assert pipeline.ytdlp_cookie_args(_Cfg(browser="chrome")) == [
        "--cookies-from-browser", "chrome"
    ]


def test_cookie_file_wins_over_browser(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    args = pipeline.ytdlp_cookie_args(_Cfg(browser="chrome", file=str(cookies)))
    assert args == ["--cookies", str(cookies)]


def test_missing_cookie_file_falls_back_to_browser(tmp_path):
    missing = tmp_path / "nope.txt"
    args = pipeline.ytdlp_cookie_args(_Cfg(browser="edge", file=str(missing)))
    assert args == ["--cookies-from-browser", "edge"]


# ── Error hints ──────────────────────────────────────────────────────────
def test_hint_for_locked_or_encrypted_cookie_db():
    out = "ERROR: Could not copy Chrome cookie database. See ... for more info"
    hint = pipeline._ytdlp_error_hint(out, had_cookies=True)
    assert "cookies.txt" in hint.lower()
    assert "schließen" in hint.lower()


def test_hint_for_bot_wall_with_cookies():
    out = "Sign in to confirm you're not a bot"
    hint = pipeline._ytdlp_error_hint(out, had_cookies=True)
    assert "cookies" in hint.lower()


def test_hint_for_bot_wall_without_cookies():
    out = "Please sign in to confirm you are not a bot"
    hint = pipeline._ytdlp_error_hint(out, had_cookies=False)
    assert "config.json" in hint


def test_no_hint_for_unknown_error():
    assert pipeline._ytdlp_error_hint("some unrelated failure", False) == ""
