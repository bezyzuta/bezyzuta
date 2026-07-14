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


# ── download_gameplay cookie-retry strategy ──────────────────────────────────
import tempfile
from pathlib import Path
from unittest import mock


def _proc(rc, err=""):
    return mock.Mock(returncode=rc, stdout="", stderr=err)


def _write_mp4(cmd):
    out_dir = Path(cmd[cmd.index("-o") + 1]).parent
    (out_dir / "vid.mp4").write_bytes(b"x" * 2048)


def test_public_video_downloads_clean_without_touching_cookies():
    calls = []

    def run(cmd, *a, **k):
        calls.append(cmd)
        _write_mp4(cmd)
        return _proc(0)

    with tempfile.TemporaryDirectory() as d:
        with mock.patch("subprocess.run", side_effect=run):
            out = pipeline.download_gameplay(
                "http://yt/x", Path(d),
                cookies=["--cookies-from-browser", "chrome"])
    assert out.name == "vid.mp4"
    assert len(calls) == 1
    assert "--cookies-from-browser" not in calls[0]


def test_botwall_triggers_cookie_retry():
    calls = []

    def run(cmd, *a, **k):
        calls.append(cmd)
        if len(calls) == 1:
            return _proc(1, "Sign in to confirm you're not a bot. Use --cookies")
        _write_mp4(cmd)
        return _proc(0)

    with tempfile.TemporaryDirectory() as d:
        with mock.patch("subprocess.run", side_effect=run):
            out = pipeline.download_gameplay(
                "http://yt/x", Path(d),
                cookies=["--cookies-from-browser", "chrome"])
    assert out.name == "vid.mp4"
    assert len(calls) == 2
    assert "--cookies-from-browser" not in calls[0]
    assert "--cookies-from-browser" in calls[1]


def test_non_botwall_error_does_not_retry_with_cookies():
    calls = []

    def run(cmd, *a, **k):
        calls.append(cmd)
        return _proc(1, "ERROR: Video unavailable. This video is private.")

    with tempfile.TemporaryDirectory() as d:
        with mock.patch("subprocess.run", side_effect=run):
            try:
                pipeline.download_gameplay(
                    "http://yt/x", Path(d),
                    cookies=["--cookies-from-browser", "chrome"])
                assert False, "should have raised"
            except RuntimeError:
                pass
    assert len(calls) == 1  # cookies would not help a private video
