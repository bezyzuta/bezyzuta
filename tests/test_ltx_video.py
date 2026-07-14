"""Tests for the LTX-Video image-to-video helper. The actual diffusion runs in
a separate venv on a GPU and can't run in CI, so these cover the logic:
missing-venv errors, dimension/frame rounding, the motion prompt, and the
subprocess command construction (mocked)."""

import types
from pathlib import Path
from unittest import mock

import ltx_video as L


def _cfg(tmp_path, **over):
    py = tmp_path / "python.exe"; py.write_text("")
    base = dict(ltxv_python=str(py), ltxv_model="Lightricks/LTX-Video",
                ltxv_width=480, ltxv_height=832, ltxv_frames=97,
                ltxv_steps=30, ltxv_fps=24)
    base.update(over)
    return types.SimpleNamespace(**base)


class TestGuards:
    def test_missing_python_path_raises(self, tmp_path):
        cfg = types.SimpleNamespace(ltxv_python="")
        try:
            L.animate_image(tmp_path / "i.png", tmp_path / "o.mp4", "x", cfg)
            assert False
        except RuntimeError as e:
            assert "ltxv_python" in str(e)

    def test_nonexistent_interpreter_raises(self, tmp_path):
        cfg = types.SimpleNamespace(ltxv_python=str(tmp_path / "nope.exe"))
        try:
            L.animate_image(tmp_path / "i.png", tmp_path / "o.mp4", "x", cfg)
            assert False
        except RuntimeError as e:
            assert "Interpreter" in str(e)


class TestMotionPrompt:
    def test_includes_theme_and_motion(self):
        p = L._motion_prompt("lonely city at night")
        assert "lonely city at night" in p
        assert "camera" in p.lower()


class TestCommandConstruction:
    def test_rounds_dims_and_frames_and_builds_cmd(self, tmp_path):
        cfg = _cfg(tmp_path, ltxv_width=470, ltxv_height=830, ltxv_frames=100)
        seen = {}

        out = tmp_path / "o.mp4"

        def fake_run(cmd, *a, **k):
            seen["cmd"] = cmd
            Path(out).write_bytes(b"x" * 4096)   # emulate the child writing the clip
            return mock.Mock(returncode=0, stdout="OK", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            got = L.animate_image(tmp_path / "i.png", out, "moody", cfg)
        assert got == out
        cmd = seen["cmd"]
        # argv layout: [py, -c, CODE, img, prompt, out, frames, w, h, steps, fps, model]
        frames, w, h = cmd[6], cmd[7], cmd[8]
        assert int(w) % 32 == 0 and int(h) % 32 == 0          # rounded to /32
        assert (int(frames) - 1) % 8 == 0                      # rounded to 8k+1
        assert cmd[-1] == "Lightricks/LTX-Video"

    def test_failure_raises_for_fallback(self, tmp_path):
        cfg = _cfg(tmp_path)
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="", stderr="CUDA OOM")):
            try:
                L.animate_image(tmp_path / "i.png", tmp_path / "o.mp4", "x", cfg)
                assert False
            except RuntimeError as e:
                assert "LTX-Video" in str(e)
