"""Tests for the Telegram bot's pure parsing/job-building logic. No network,
no Telegram, no rendering — just the message → spec → job transform."""

import bot


class _Cfg:
    def __init__(self):
        self.tts_language = "auto"
        self.target_w = 1080
        self.target_h = 1920
        self.telegram_music_dir = ""
        self.telegram_sfx_dir = ""


class TestParseMessage:
    def test_keys_and_multiline_script(self):
        msg = ("url: https://youtu.be/x\nlang: de\nhook: KRASS\n"
               "script:\nLine one\nLine two")
        spec = bot._parse_message(msg)
        assert spec["url"] == "https://youtu.be/x"
        assert spec["lang"] == "de"
        assert spec["hook"] == "KRASS"
        assert spec["script"] == "Line one\nLine two"

    def test_script_inline_after_colon(self):
        spec = bot._parse_message("script: just one line")
        assert spec["script"] == "just one line"

    def test_no_script(self):
        spec = bot._parse_message("url: http://x\nlang: en")
        assert "script" not in spec and spec["lang"] == "en"


class TestEffectsPreset:
    def test_presets(self):
        assert bot._effects_from_spec("none") == []
        assert "horror_grade" in bot._effects_from_spec("horror")
        assert "horror_grade" not in bot._effects_from_spec("all-no-horror")
        assert "color_grade" in bot._effects_from_spec("all-no-horror")
        # 'all' includes horror
        assert "glitch" in bot._effects_from_spec("all")

    def test_custom_comma_list(self):
        assert bot._effects_from_spec("flash, shake, punch") == ["flash", "shake", "punch"]

    def test_default_is_no_horror(self):
        assert bot._effects_from_spec("") == bot._FX_ALL_NO_HORROR


class TestBuildJob:
    def test_short_with_url(self):
        cfg = _Cfg()
        job = bot._build_job_and_cfg(
            {"url": "http://yt/x", "lang": "de", "script": "Hallo", "effects": "all-no-horror"}, cfg)
        assert (cfg.target_w, cfg.target_h) == (1080, 1920)
        assert job["source_url"] == "http://yt/x"
        assert job["faceless_mode"] is False
        assert job["auto_reframe"] is True
        assert job["script"] == "Hallo"
        assert cfg.tts_language == "de"

    def test_faceless_needs_no_url(self):
        cfg = _Cfg()
        job = bot._build_job_and_cfg({"format": "faceless", "script": "Story"}, cfg)
        assert (cfg.target_w, cfg.target_h) == (1920, 1080)
        assert "source_url" not in job
        assert job["faceless_mode"] is True
        assert job["images_continuous"] is True

    def test_long_autoextends_and_landscape(self):
        cfg = _Cfg()
        job = bot._build_job_and_cfg({"format": "long", "url": "http://yt/x", "script": "s"}, cfg)
        assert (cfg.target_w, cfg.target_h) == (1920, 1080)
        assert job["extend_script"] is True
        assert job["target_duration"] == 480.0

    def test_music_only_when_dir_configured(self):
        cfg = _Cfg()
        job = bot._build_job_and_cfg({"url": "http://yt/x", "music": "track.mp3", "script": "s"}, cfg)
        assert "enable_music" not in job          # no dir → ignored
        cfg2 = _Cfg(); cfg2.telegram_music_dir = "/music"
        job2 = bot._build_job_and_cfg({"url": "http://yt/x", "music": "track.mp3", "script": "s"}, cfg2)
        assert job2["enable_music"] is True and job2["music_track"] == "track.mp3"

    def test_effects_default_no_horror(self):
        cfg = _Cfg()
        job = bot._build_job_and_cfg({"url": "http://yt/x", "script": "s"}, cfg)
        assert "horror_grade" not in job["effects_enabled"]
        assert "color_grade" in job["effects_enabled"]
