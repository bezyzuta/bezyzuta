"""External-venv voice tools: F5-TTS cloning + Resemble/DeepFilter enhance.

The heavy venvs aren't present in CI, so subprocess + ffmpeg are mocked; these
cover the wiring, the safe fallbacks, and config parsing.
Run: `pytest tests/test_external_voice.py -v`
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pipeline


class _Cfg:
    def __init__(self, **kw):
        self.external_tts = kw.get("external_tts", "f5")
        self.external_tts_python = kw.get("external_tts_python", "")
        self.external_tts_ref_text = kw.get("external_tts_ref_text", "")
        self.voice_enhance = kw.get("voice_enhance", "off")
        self.voice_enhance_python = kw.get("voice_enhance_python", "")


def _fake_py(tmp_path):
    p = tmp_path / "venv_python"
    p.write_text("#!/bin/sh\n")
    return str(p)


# ── F5-TTS ───────────────────────────────────────────────────────────────
class TestF5:
    def test_missing_python_raises(self, tmp_path):
        ref = tmp_path / "r.wav"; ref.write_bytes(b"x" * 1000)
        with pytest.raises(RuntimeError, match="external_tts_python"):
            pipeline.synthesize_voiceover_f5(
                "hi", _Cfg(external_tts_python=""), tmp_path / "o.mp3", str(ref))

    def test_missing_reference_raises(self, tmp_path):
        cfg = _Cfg(external_tts_python=_fake_py(tmp_path))
        with pytest.raises(RuntimeError, match="reference audio"):
            pipeline.synthesize_voiceover_f5("hi", cfg, tmp_path / "o.mp3", "")

    def test_success_transcodes_to_mp3(self, tmp_path):
        ref = tmp_path / "r.wav"; ref.write_bytes(b"x" * 1000)
        out = tmp_path / "voice.mp3"
        cfg = _Cfg(external_tts_python=_fake_py(tmp_path))

        def fake_subrun(cmd, **k):
            Path(cmd[-1]).write_bytes(b"w" * 2000)   # the F5 wav (last argv)
            return MagicMock(returncode=0, stderr="")

        def fake_run(cmd, **k):
            Path(cmd[-1]).write_bytes(b"m" * 2000)   # ffmpeg transcode output

        with patch("subprocess.run", side_effect=fake_subrun), \
             patch.object(pipeline, "run", side_effect=fake_run):
            res = pipeline.synthesize_voiceover_f5("hello world", cfg, out, str(ref))
        assert res == out and out.is_file()

    def test_no_audio_raises_for_fallback(self, tmp_path):
        ref = tmp_path / "r.wav"; ref.write_bytes(b"x" * 1000)
        cfg = _Cfg(external_tts_python=_fake_py(tmp_path))
        # subprocess "runs" but writes no wav -> must raise so caller falls back.
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="boom")):
            with pytest.raises(RuntimeError, match="no audio"):
                pipeline.synthesize_voiceover_f5("hi", cfg, tmp_path / "o.mp3", str(ref))


# ── Voice enhance ──────────────────────────────────────────────────────────
class TestEnhance:
    def test_off_returns_input(self, tmp_path):
        src = tmp_path / "v.mp3"; src.write_bytes(b"x" * 1000)
        cfg = _Cfg(voice_enhance="off")
        assert pipeline.enhance_voice_external(src, tmp_path / "o.mp3", cfg) == src

    def test_missing_venv_returns_input(self, tmp_path):
        src = tmp_path / "v.mp3"; src.write_bytes(b"x" * 1000)
        cfg = _Cfg(voice_enhance="resemble", voice_enhance_python="")
        assert pipeline.enhance_voice_external(src, tmp_path / "o.mp3", cfg) == src

    def test_success_returns_enhanced(self, tmp_path):
        src = tmp_path / "v.mp3"; src.write_bytes(b"x" * 1000)
        out = tmp_path / "o.mp3"
        cfg = _Cfg(voice_enhance="deepfilter", voice_enhance_python=_fake_py(tmp_path))

        def fake_subrun(cmd, **k):
            Path(cmd[-1]).write_bytes(b"w" * 2000)
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_subrun), \
             patch.object(pipeline, "run",
                          side_effect=lambda cmd, **k: Path(cmd[-1]).write_bytes(b"m" * 2000)):
            res = pipeline.enhance_voice_external(src, out, cfg)
        assert res == out and out.is_file()

    def test_subprocess_failure_returns_input(self, tmp_path):
        src = tmp_path / "v.mp3"; src.write_bytes(b"x" * 1000)
        cfg = _Cfg(voice_enhance="resemble", voice_enhance_python=_fake_py(tmp_path))
        with patch("subprocess.run", side_effect=RuntimeError("crash")):
            assert pipeline.enhance_voice_external(src, tmp_path / "o.mp3", cfg) == src


# ── Config parsing ─────────────────────────────────────────────────────────
def test_config_defaults_off(tmp_path):
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"output_dir": str(tmp_path)}), encoding="utf-8")
    cfg = pipeline.Config.load(p)
    assert cfg.external_tts == "off"
    assert cfg.voice_enhance == "off"


def test_config_reads_external_voice(tmp_path):
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "output_dir": str(tmp_path),
        "external_tts": "F5", "external_tts_python": r"C:\v\python.exe",
        "voice_enhance": "Resemble", "voice_enhance_python": r"C:\e\python.exe",
    }), encoding="utf-8")
    cfg = pipeline.Config.load(p)
    assert cfg.external_tts == "f5"
    assert cfg.external_tts_python == r"C:\v\python.exe"
    assert cfg.voice_enhance == "resemble"


import pytest  # noqa: E402  (used by the raises tests above)
