"""Tests for the local Grok Build CLI image provider: fetch_image_from_grok_cli()
and its ~/.grok snapshot-diff. All subprocess / filesystem-home calls are
mocked — no real `grok` CLI or SuperGrok subscription needed.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

import pipeline


class _Cfg:
    """Minimal stand-in for pipeline.Config (grok fields only)."""
    def __init__(self, **kw):
        self.use_grok_cli = kw.get("use_grok_cli", True)
        self.grok_cli_path = kw.get("grok_cli_path", "grok")
        self.grok_cli_extra_args = kw.get("grok_cli_extra_args", "")


@pytest.fixture(autouse=True)
def _reset_cli_cache():
    pipeline._GROK_CLI_PATH = None
    yield
    pipeline._GROK_CLI_PATH = None


def _completed(stdout="", returncode=0, stderr=""):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def _write_jpg(path: Path, color=(200, 50, 50)):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Noise so the JPEG is comfortably > 1KB (_save_square_image rejects
    # tiny/truncated files), and non-square so the squaring is observable.
    im = Image.frombytes("RGB", (256, 192), os.urandom(256 * 192 * 3))
    im.save(path, "JPEG", quality=90)


def _grok_run_that_writes(home: Path, color=(200, 50, 50)):
    """Return a subprocess.run side-effect that drops a fresh image into the
    fake ~/.grok session images dir, mimicking a real `grok` image gen."""
    img = home / ".grok" / "sessions" / "cwd" / "uuid" / "images" / "1.jpg"

    def _side_effect(*args, **kwargs):
        _write_jpg(img, color)
        return _completed(stdout="Fertig! gespeichert unter …/images/1.jpg")
    return _side_effect, img


class TestFetchImageFromGrokCli:
    def test_not_installed_raises(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="grok CLI not found"):
                pipeline.fetch_image_from_grok_cli("a cat", tmp_path / "out.png", _Cfg())

    def test_new_image_is_picked_up_and_squared(self, tmp_path):
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        side_effect, _img = _grok_run_that_writes(home)
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=side_effect):
            result = pipeline.fetch_image_from_grok_cli("a cat", out, _Cfg())
        assert result == out
        assert out.is_file()
        # _save_square_image normalizes to a square RGBA PNG.
        with Image.open(out) as im:
            assert im.width == im.height

    def test_ignores_preexisting_images(self, tmp_path):
        """A file that existed BEFORE the run must not be mistaken for output."""
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        stale = home / ".grok" / "sessions" / "old" / "images" / "9.jpg"
        _write_jpg(stale, color=(10, 10, 10))
        # The run produces nothing new.
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", return_value=_completed(stdout="hmm")):
            with pytest.raises(RuntimeError, match="no new image"):
                pipeline.fetch_image_from_grok_cli("a cat", out, _Cfg())

    def test_nonzero_exit_raises(self, tmp_path):
        home = tmp_path / "home"
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
            with pytest.raises(RuntimeError, match="exited 1"):
                pipeline.fetch_image_from_grok_cli("a cat", tmp_path / "out.png", _Cfg())

    def test_aspect_9_16_makes_portrait_and_requests_it(self, tmp_path):
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        side_effect, _img = _grok_run_that_writes(home)
        captured = {}

        def _spy(*args, **kwargs):
            captured["cmd"] = args[0]
            return side_effect(*args, **kwargs)

        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=_spy):
            pipeline.fetch_image_from_grok_cli("a cat", out, _Cfg(), aspect="9:16")
        # The grok prompt asks for a 9:16 vertical image …
        prompt_arg = captured["cmd"][captured["cmd"].index("-p") + 1]
        assert "9:16 vertical portrait" in prompt_arg
        # … and the saved file is actually taller than wide (crop-to-fill).
        with Image.open(out) as im:
            assert im.height > im.width

    def test_default_aspect_still_square(self, tmp_path):
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        side_effect, _img = _grok_run_that_writes(home)
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=side_effect):
            pipeline.fetch_image_from_grok_cli("a cat", out, _Cfg())
        with Image.open(out) as im:
            assert im.width == im.height

    def test_timeout_raises(self, tmp_path):
        home = tmp_path / "home"
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("grok", 240)):
            with pytest.raises(RuntimeError, match="timed out"):
                pipeline.fetch_image_from_grok_cli("a cat", tmp_path / "out.png", _Cfg())

    def test_prompt_passed_as_p_value(self, tmp_path):
        """Grok Build's -p (alias --single) takes the prompt as its argv VALUE,
        not on stdin — so the prompt must be the element right after -p."""
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        side_effect, _img = _grok_run_that_writes(home)
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=side_effect) as run_mock:
            pipeline.fetch_image_from_grok_cli("a royal roblox avatar", out, _Cfg())
        cmd = run_mock.call_args[0][0]
        kwargs = run_mock.call_args[1]
        assert "-p" in cmd
        # prompt is the value immediately after -p, and includes our text
        p_val = cmd[cmd.index("-p") + 1]
        assert "a royal roblox avatar" in p_val
        # nothing shoved onto stdin
        assert kwargs.get("input", "") == ""

    def test_extra_args_are_appended(self, tmp_path):
        home = tmp_path / "home"
        out = tmp_path / "out.png"
        side_effect, _img = _grok_run_that_writes(home)
        with patch("shutil.which", return_value="/usr/bin/grok"), \
             patch("pathlib.Path.home", return_value=home), \
             patch("subprocess.run", side_effect=side_effect) as run_mock:
            pipeline.fetch_image_from_grok_cli(
                "a cat", out, _Cfg(grok_cli_extra_args="--yolo --no-tui"))
        cmd = run_mock.call_args[0][0]
        assert "--yolo" in cmd and "--no-tui" in cmd


class TestResolveGrokCli:
    def test_explicit_path_wins(self, tmp_path):
        exe = tmp_path / "grok"
        exe.write_text("#!/bin/sh\n")
        assert pipeline._resolve_grok_cli(str(exe)) == str(exe)

    def test_missing_returns_empty(self):
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            assert pipeline._resolve_grok_cli("grok") == ""


# ── black/blank image rejection (the "2 black middle images" bug) ────────────
import io as _io
import tempfile as _tf
from pathlib import Path as _PP


def _jpg(color, size=(640, 640)):
    from PIL import Image
    b = _io.BytesIO()
    Image.new("RGB", size, color).save(b, "JPEG")
    return b.getvalue()


def test_black_image_rejected_by_save_square():
    import pipeline
    with _tf.TemporaryDirectory() as d:
        out = _PP(d) / "o.png"
        assert pipeline._save_square_image(_jpg((0, 0, 0)), out) is False


def test_black_image_rejected_by_save_aspect():
    import pipeline
    with _tf.TemporaryDirectory() as d:
        out = _PP(d) / "o.png"
        assert pipeline._save_aspect_image(_jpg((0, 0, 0)), out) is False


def test_flat_grey_rejected():
    import pipeline
    with _tf.TemporaryDirectory() as d:
        out = _PP(d) / "o.png"
        assert pipeline._save_square_image(_jpg((128, 128, 128)), out) is False


def test_dark_image_with_bright_content_is_kept():
    import pipeline
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 640), (2, 2, 2))
    ImageDraw.Draw(im).ellipse((300, 300, 340, 340), fill=(255, 255, 255))
    b = _io.BytesIO(); im.save(b, "JPEG")
    with _tf.TemporaryDirectory() as d:
        out = _PP(d) / "o.png"
        assert pipeline._save_square_image(b.getvalue(), out) is True
