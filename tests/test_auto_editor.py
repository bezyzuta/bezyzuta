"""Tests for the opt-in auto-editor silence-cutting step. The auto-editor
package isn't installed in CI, so these focus on the command construction
and the graceful-fallback paths (a render must never break because of it)."""

import subprocess
from pathlib import Path
from unittest import mock

import pipeline as p


def _make_fake_video(path: Path) -> None:
    path.write_bytes(b"\x00" * 4096)


class TestAutoEditorFallback:
    def test_missing_package_returns_false_and_keeps_original(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        original = vid.read_bytes()
        msgs = []
        # Simulate `python -m auto_editor` with the package absent.
        fake = mock.Mock(returncode=1, stderr="No module named auto_editor", stdout="")
        with mock.patch("subprocess.run", return_value=fake):
            result = p.apply_auto_editor(vid, on_step=msgs.append)
        assert result is False
        assert vid.read_bytes() == original  # untouched
        assert any("nicht installiert" in m for m in msgs)

    def test_filenotfound_is_caught(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            assert p.apply_auto_editor(vid) is False

    def test_timeout_is_caught(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        with mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired("cmd", 900)):
            assert p.apply_auto_editor(vid) is False

    def test_empty_result_keeps_original(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        original = vid.read_bytes()
        msgs = []
        fake = mock.Mock(returncode=1,
                         stderr="Error: Editing resulted in an empty file", stdout="")
        with mock.patch("subprocess.run", return_value=fake):
            result = p.apply_auto_editor(vid, on_step=msgs.append)
        assert result is False
        assert vid.read_bytes() == original


class TestAutoEditorCommand:
    def test_command_has_threshold_and_margin(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        captured = {}

        def fake_run(cmd, *a, **kw):
            captured["cmd"] = cmd
            return mock.Mock(returncode=1, stderr="No module named auto_editor", stdout="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            p.apply_auto_editor(vid, margin=0.25, threshold=0.06)
        cmd = captured["cmd"]
        assert "-m" in cmd and "auto_editor" in cmd
        joined = " ".join(cmd)
        assert "audio:threshold=6%" in joined
        assert "0.25sec" in joined
        assert "--no-open" in joined

    def test_threshold_clamped_to_unit_range(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)
        captured = {}

        def fake_run(cmd, *a, **kw):
            captured["cmd"] = cmd
            return mock.Mock(returncode=1, stderr="No module named auto_editor", stdout="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            p.apply_auto_editor(vid, threshold=5.0)  # nonsense -> clamp to 1.0
        assert "audio:threshold=100%" in " ".join(captured["cmd"])


class TestAutoEditorSuccess:
    def test_success_replaces_video_in_place(self, tmp_path):
        vid = tmp_path / "out.mp4"
        _make_fake_video(vid)

        def fake_run(cmd, *a, **kw):
            # auto-editor writes its --output target; emulate that.
            out_idx = cmd.index("--output") + 1
            Path(cmd[out_idx]).write_bytes(b"\x01" * 8192)
            return mock.Mock(returncode=0, stderr="", stdout="")

        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch("pipeline._media_duration", side_effect=[30.0, 22.0]):
            result = p.apply_auto_editor(vid)
        assert result is True
        assert vid.read_bytes() == b"\x01" * 8192  # replaced by the trimmed file
