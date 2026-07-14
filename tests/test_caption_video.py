"""Tests for the 'eigenes Video + Untertitel' mode. ffmpeg/whisper are mocked
(none run in CI); these cover the guards, dimension probing, and the
orchestration (transcribe → centered ASS → burn)."""

import types
from pathlib import Path
from unittest import mock

import caption_video as C


def _cfg(tmp_path):
    return types.SimpleNamespace(
        output_dir=str(tmp_path), whisper_model="base", whisperx_python="")


class TestGuards:
    def test_no_video_path_raises(self, tmp_path):
        try:
            C.run_caption_video({"slug": "x"}, _cfg(tmp_path))
            assert False
        except RuntimeError as e:
            assert "hochgeladen" in str(e) or "caption_video_path" in str(e)

    def test_missing_file_raises(self, tmp_path):
        job = {"slug": "x", "caption_video_path": str(tmp_path / "nope.mp4")}
        try:
            C.run_caption_video(job, _cfg(tmp_path))
            assert False
        except RuntimeError as e:
            assert "nicht gefunden" in str(e)


class TestProbeDimensions:
    def test_parses_ffprobe(self, tmp_path):
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(stdout="1080x1920\n", returncode=0)):
            assert C._probe_dimensions(tmp_path / "v.mp4") == (1080, 1920)

    def test_fallback_on_error(self, tmp_path):
        with mock.patch("subprocess.run", side_effect=Exception("boom")):
            assert C._probe_dimensions(tmp_path / "v.mp4") == (1080, 1920)


class TestOrchestration:
    def test_transcribes_centered_and_burns(self, tmp_path):
        vid = tmp_path / "canva.mp4"; vid.write_bytes(b"x" * 4096)
        job = {"slug": "myvid", "caption_video_path": str(vid)}
        cfg = _cfg(tmp_path)
        calls = {"ass_pos": None, "burned": False}

        def fake_write_ass(words, w, h, out, **kw):
            calls["ass_pos"] = kw.get("caption_position")
            Path(out).write_text("[Events]\n")

        def fake_run_capture(cmd, *a, **k):
            if "subtitles" in " ".join(cmd):
                calls["burned"] = True
            return mock.Mock(returncode=0)

        with mock.patch.object(C.P, "run_capture_stderr", side_effect=fake_run_capture), \
             mock.patch.object(C, "_probe_dimensions", return_value=(1080, 1920)), \
             mock.patch.object(C.P, "transcribe_words_best",
                               return_value=([(0, 1, "hallo")], "cuda")), \
             mock.patch.object(C.P, "write_ass", side_effect=fake_write_ass), \
             mock.patch.object(C.P, "probe_duration", return_value=20.0):
            out = C.run_caption_video(job, cfg)
        assert out.name == "myvid.mp4"
        assert calls["ass_pos"] == "center"   # text in the middle
        assert calls["burned"] is True

    def test_continues_without_text_when_transcribe_fails(self, tmp_path):
        vid = tmp_path / "canva.mp4"; vid.write_bytes(b"x" * 4096)
        job = {"slug": "v2", "caption_video_path": str(vid)}
        cfg = _cfg(tmp_path)
        seen = {}

        def fake_write_ass(words, w, h, out, **kw):
            seen["enabled"] = kw.get("enable_captions")
            Path(out).write_text("[Events]\n")

        with mock.patch.object(C.P, "run_capture_stderr", return_value=mock.Mock(returncode=0)), \
             mock.patch.object(C, "_probe_dimensions", return_value=(1080, 1920)), \
             mock.patch.object(C.P, "transcribe_words_best",
                               side_effect=RuntimeError("whisper down")), \
             mock.patch.object(C.P, "write_ass", side_effect=fake_write_ass), \
             mock.patch.object(C.P, "probe_duration", return_value=20.0):
            out = C.run_caption_video(job, cfg)
        assert out.name == "v2.mp4"
        assert seen["enabled"] is False   # no words → captions disabled, video still made
