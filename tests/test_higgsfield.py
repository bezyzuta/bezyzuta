"""Tests for the Higgsfield AI-video provider: _higgsfield_result_url (JSON
parse) and fetch_video_from_higgsfield (CLI create→wait→download flow).
All subprocess / network / ffmpeg calls are mocked."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import pipeline


class _Cfg:
    def __init__(self, **kw):
        self.use_higgsfield = kw.get("use_higgsfield", True)
        self.higgsfield_cli_path = kw.get("higgsfield_cli_path", "higgsfield")
        self.higgsfield_video_model = kw.get("higgsfield_video_model", "some_video_model")
        self.higgsfield_extra_args = kw.get("higgsfield_extra_args", "")


@pytest.fixture(autouse=True)
def _reset_cache():
    pipeline._HIGGSFIELD_CLI_PATH = None
    yield
    pipeline._HIGGSFIELD_CLI_PATH = None


def _completed(stdout="", returncode=0, stderr=""):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestResultUrlParse:
    def test_completed_array(self):
        j = '[{"status":"completed","result_url":"https://cdn/clip.mp4"}]'
        assert pipeline._higgsfield_result_url(j) == "https://cdn/clip.mp4"

    def test_single_object(self):
        j = '{"status":"succeeded","result_url":"https://cdn/x.mp4"}'
        assert pipeline._higgsfield_result_url(j) == "https://cdn/x.mp4"

    def test_empty_and_pending_and_garbage(self):
        assert pipeline._higgsfield_result_url("[]") == ""
        assert pipeline._higgsfield_result_url(
            '[{"status":"processing","result_url":null}]') == ""
        assert pipeline._higgsfield_result_url("not json") == ""

    def test_skips_pending_takes_completed(self):
        j = ('[{"status":"processing","result_url":null},'
             '{"status":"completed","result_url":"https://cdn/ok.mp4"}]')
        assert pipeline._higgsfield_result_url(j) == "https://cdn/ok.mp4"


class TestFetchVideoFromHiggsfield:
    def test_cli_not_found_raises(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="higgsfield CLI not found"):
                pipeline.fetch_video_from_higgsfield("x", tmp_path / "o.mp4", _Cfg())

    def test_model_unset_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/higgsfield"):
            with pytest.raises(RuntimeError, match="higgsfield_video_model not set"):
                pipeline.fetch_video_from_higgsfield(
                    "x", tmp_path / "o.mp4", _Cfg(higgsfield_video_model=""))

    def test_success_downloads_and_transcodes(self, tmp_path):
        out = tmp_path / "o.mp4"
        stdout = '[{"status":"completed","result_url":"https://cdn/clip.mp4"}]'

        # requests.get streams the "video" bytes; ffmpeg (run) writes the final.
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.iter_content = lambda chunk_size=0: [b"x" * 20000]
        resp.__enter__ = lambda s: resp
        resp.__exit__ = lambda *a: False

        def fake_run(cmd, **kw):
            # mimic ffmpeg producing the out file
            out.write_bytes(b"y" * 20000)
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout=stdout)) as run_mock, \
             patch("pipeline.requests.get", return_value=resp), \
             patch("pipeline.run", side_effect=fake_run):
            result = pipeline.fetch_video_from_higgsfield("a foggy hallway", out, _Cfg())
        assert result == out
        # verify the CLI was called with create/--wait/--json + the model + prompt
        cmd = run_mock.call_args[0][0]
        assert "create" in cmd and "--wait" in cmd and "--json" in cmd
        assert "some_video_model" in cmd
        assert "a foggy hallway" in cmd

    def test_no_result_url_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout="[]")):
            with pytest.raises(RuntimeError, match="no completed result_url"):
                pipeline.fetch_video_from_higgsfield("x", tmp_path / "o.mp4", _Cfg())

    def test_non_video_result_raises(self, tmp_path):
        # result is a PNG (image model picked by mistake) → reject so caller
        # falls back rather than overlaying a still as a "video".
        stdout = '[{"status":"completed","result_url":"https://cdn/x.png"}]'
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout=stdout)):
            with pytest.raises(RuntimeError, match="not a video"):
                pipeline.fetch_video_from_higgsfield("x", tmp_path / "o.mp4", _Cfg())

    def test_nonzero_exit_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
            with pytest.raises(RuntimeError, match="exited 1"):
                pipeline.fetch_video_from_higgsfield("x", tmp_path / "o.mp4", _Cfg())

    def test_timeout_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("higgsfield", 600)):
            with pytest.raises(RuntimeError, match="timed out"):
                pipeline.fetch_video_from_higgsfield("x", tmp_path / "o.mp4", _Cfg())


class _ImgCfg:
    def __init__(self, **kw):
        self.use_higgsfield_images = kw.get("use_higgsfield_images", True)
        self.higgsfield_cli_path = kw.get("higgsfield_cli_path", "higgsfield")
        self.higgsfield_image_model = kw.get("higgsfield_image_model", "nano_banana_2")
        self.higgsfield_image_extra_args = kw.get("higgsfield_image_extra_args", "")


def _png_bytes(size=(800, 800)):
    from PIL import Image
    import io, os
    buf = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, "PNG")
    return buf.getvalue()


class TestFetchImageFromHiggsfield:
    def test_success_square(self, tmp_path):
        out = tmp_path / "img.png"
        stdout = '[{"status":"completed","result_url":"https://cdn/x.png"}]'
        resp = MagicMock(); resp.raise_for_status = lambda: None; resp.content = _png_bytes()
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout=stdout)) as run_mock, \
             patch("pipeline.requests.get", return_value=resp):
            r = pipeline.fetch_image_from_higgsfield("a stickman", out, _ImgCfg())
        assert r == out and out.is_file()
        cmd = run_mock.call_args[0][0]
        assert "create" in cmd and "nano_banana_2" in cmd and "a stickman" in cmd
        from PIL import Image
        with Image.open(out) as im:
            assert im.width == im.height  # square for non-faceless

    def test_success_faceless_16_9(self, tmp_path):
        out = tmp_path / "img.png"
        stdout = '[{"status":"completed","result_url":"https://cdn/x.png"}]'
        resp = MagicMock(); resp.raise_for_status = lambda: None; resp.content = _png_bytes((1000, 1000))
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout=stdout)), \
             patch("pipeline.requests.get", return_value=resp):
            pipeline.fetch_image_from_higgsfield("a stickman", out, _ImgCfg(), faceless_wide=True)
        from PIL import Image
        with Image.open(out) as im:
            assert abs(im.width / im.height - 16 / 9) < 0.02

    def test_cli_missing_raises(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="higgsfield CLI not found"):
                pipeline.fetch_image_from_higgsfield("x", tmp_path / "o.png", _ImgCfg())

    def test_non_image_result_raises(self, tmp_path):
        stdout = '[{"status":"completed","result_url":"https://cdn/x.mp4"}]'
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(stdout=stdout)):
            with pytest.raises(RuntimeError, match="not an image"):
                pipeline.fetch_image_from_higgsfield("x", tmp_path / "o.png", _ImgCfg())

    def test_nonzero_exit_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/higgsfield"), \
             patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
            with pytest.raises(RuntimeError, match="exited 1"):
                pipeline.fetch_image_from_higgsfield("x", tmp_path / "o.png", _ImgCfg())
