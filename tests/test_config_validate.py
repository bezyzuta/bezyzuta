"""Coverage for Config.validate(). Reads/writes temp config files so it
can exercise the real load path end to end."""

import json
import os
from pathlib import Path

import pytest

import pipeline


# Minimum keys for a config that loads without raising.
_MIN_CONFIG = {
    "output_dir": "",  # filled per-test (uses tmp_path)
    "gemini_api_key": "AIza_test_key_not_real",
    "cloudflare_account_id": "",
    "cloudflare_api_token": "",
}


def _write_config(tmp_path: Path, extra: dict | None = None) -> Path:
    cfg = dict(_MIN_CONFIG)
    cfg["output_dir"] = str(tmp_path / "out")
    if extra:
        cfg.update(extra)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Don't let the test machine's real GEMINI_API_KEY env leak in and
    mask the "missing key" assertion."""
    for var in ("GEMINI_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


class TestConfigValidate:
    def test_minimal_config_passes(self, tmp_path):
        cfg = pipeline.Config.load(_write_config(tmp_path))
        errors, warnings = cfg.validate()
        assert errors == [], errors
        # cloudflare-not-set is expected on a minimal config → 1 warning.
        assert any("cloudflare" in w.lower() for w in warnings)

    def test_missing_gemini_is_error(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"gemini_api_key": ""})
        )
        errors, _ = cfg.validate()
        assert any("gemini_api_key" in e for e in errors)

    def test_missing_gemini_ok_when_claude_cli_on(self, tmp_path):
        # use_claude_cli provides a text backend, so a missing Gemini key
        # is a warning, not a hard error.
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"gemini_api_key": "", "use_claude_cli": True})
        )
        errors, warnings = cfg.validate()
        assert not any("gemini_api_key" in e for e in errors)
        assert any("claude" in w.lower() for w in warnings)

    def test_tiny_resolution_is_error(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"target_resolution": [108, 192]})
        )
        errors, _ = cfg.validate()
        assert any("target_resolution" in e for e in errors)

    def test_unknown_whisper_is_warning_not_error(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"whisper_model": "totally-fake"})
        )
        errors, warnings = cfg.validate()
        assert not any("whisper" in e.lower() for e in errors)
        assert any("whisper" in w.lower() for w in warnings)

    def test_unknown_tts_language_is_warning(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"tts_language": "fr"})
        )
        errors, warnings = cfg.validate()
        assert not errors or "gemini" in errors[0].lower()  # only gemini if at all
        assert any("tts_language" in w for w in warnings)

    def test_missing_ref_audio_is_warning(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"tts_reference_audio": "/does/not/exist.wav"})
        )
        _, warnings = cfg.validate()
        assert any("tts_reference_audio" in w for w in warnings)

    def test_out_of_range_chatterbox_knob_is_warning(self, tmp_path):
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"tts_exaggeration": 1.7})
        )
        _, warnings = cfg.validate()
        assert any("tts_exaggeration" in w for w in warnings)

    def test_output_dir_gets_created(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "out"
        cfg = pipeline.Config.load(
            _write_config(tmp_path, {"output_dir": str(target)})
        )
        cfg.validate()
        assert target.is_dir()
