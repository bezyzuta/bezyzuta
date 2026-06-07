"""Autopilot batch runner: job/cfg building, queue processing, skip-done,
upload wiring. pipeline.run_one / run_multiclip and the YouTube upload are
mocked — this verifies the orchestration, not the (untestable here) render."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import autopilot


class _Cfg:
    """Minimal stand-in for pipeline.Config."""
    def __init__(self):
        self.tts_language = "auto"
        self.image_style = "auto"
        self.use_claude_cli = False
        self.claude_cli_model = "sonnet"
        self.target_w = 1080
        self.target_h = 1920


@pytest.fixture
def fake_cfg_load():
    with patch.object(autopilot.Config, "load", return_value=_Cfg()) as m:
        yield m


# ── build_cfg / output format ────────────────────────────────────────────────
def test_output_format_portrait_vs_landscape():
    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "portrait")
    assert (cfg.target_w, cfg.target_h) == (1080, 1920)
    assert flags["no_source"] is False

    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "faceless")
    assert (cfg.target_w, cfg.target_h) == (1920, 1080)
    assert flags["no_source"] is True and flags["faceless"] is True

    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "ai_image_short")
    assert (cfg.target_w, cfg.target_h) == (1080, 1920)
    assert flags["no_source"] is True


def test_build_cfg_applies_overrides(fake_cfg_load):
    cfg = autopilot.build_cfg(
        {"tts_language": "DE", "image_style": "roblox", "use_claude_cli": True,
         "cfg_overrides": {"whisper_model": "medium"}}, "config.json")
    assert cfg.tts_language == "de"
    assert cfg.image_style == "roblox"
    assert cfg.use_claude_cli is True
    assert cfg.whisper_model == "medium"


# ── build_job ────────────────────────────────────────────────────────────────
def test_build_job_defaults_and_slug():
    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "portrait")
    job = autopilot.build_job({"topic": "Krasser Moment!!"}, cfg, flags)
    assert job["slug"] == "krasser-moment"
    assert job["topic"] == "Krasser Moment!!"
    # a default field is present
    assert job["caption_font"] == "Impact"
    # required hard-access keys exist (no KeyError in run_one)
    for k in ("slug", "scene_pick_mode", "manual_ranges", "target_duration",
              "hook_text", "normalize_audio", "resume", "voice_eq",
              "multiclip_enabled"):
        assert k in job


def test_build_job_passthrough_and_overrides():
    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "portrait")
    job = autopilot.build_job(
        {"topic": "x", "target_duration": 120, "auto_reframe": False,
         "source_url": "https://yt/watch?v=abc",
         "overrides": {"effects_ai": False, "image_count": 12}}, cfg, flags)
    assert job["target_duration"] == 120          # passthrough
    assert job["auto_reframe"] is False           # passthrough
    assert job["source_url"] == "https://yt/watch?v=abc"
    assert job["effects_ai"] is False             # overrides win
    assert job["image_count"] == 12


def test_faceless_drops_source_and_forces_continuous():
    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "faceless")
    job = autopilot.build_job(
        {"topic": "story", "source_url": "https://yt/x",
         "multiclip_enabled": True}, cfg, flags)
    assert "source_url" not in job                # no_source format ignores it
    assert job["faceless_mode"] is True
    assert job["images_continuous"] is True
    assert job["multiclip_enabled"] is False      # forced off without source


def test_upload_enabled_forces_metadata():
    cfg = _Cfg()
    flags = autopilot._apply_output_format(cfg, "portrait")
    job = autopilot.build_job(
        {"topic": "x", "youtube_metadata": False,
         "upload": {"enabled": True}}, cfg, flags)
    assert job["youtube_metadata"] is True


# ── sidecar metadata ─────────────────────────────────────────────────────────
def test_sidecar_metadata_read(tmp_path):
    vid = tmp_path / "clip.mp4"; vid.write_bytes(b"x")
    (tmp_path / "clip.mp4.youtube.json").write_text(
        json.dumps({"title": "T", "description": "D", "tags": ["a", "b"]}),
        encoding="utf-8")
    meta = autopilot._load_sidecar_metadata(vid, "fallback")
    assert meta["title"] == "T" and meta["tags"] == ["a", "b"]


def test_sidecar_metadata_fallback(tmp_path):
    vid = tmp_path / "clip.mp4"; vid.write_bytes(b"x")
    meta = autopilot._load_sidecar_metadata(vid, "Mein Thema")
    assert meta["title"] == "Mein Thema" and meta["tags"] == []


# ── run_queue orchestration ──────────────────────────────────────────────────
def _write_queue(tmp_path, jobs, **top):
    q = tmp_path / "autopilot.jobs.json"
    q.write_text(json.dumps({"config": "config.json", "jobs": jobs, **top}),
                 encoding="utf-8")
    return q


def test_run_queue_renders_and_marks_done(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{"topic": "A"}, {"topic": "B"}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one", return_value=out) as ro, \
         patch.object(autopilot, "run_multiclip") as rm:
        failures = autopilot.run_queue(q, allow_shutdown=False)
    assert failures == 0
    assert ro.call_count == 2 and rm.call_count == 0
    state = json.loads((tmp_path / "autopilot_state.json").read_text())
    assert all(r["status"] == "done" for r in state["done"].values())


def test_run_queue_skips_already_done(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{"topic": "A"}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one", return_value=out):
        autopilot.run_queue(q, allow_shutdown=False)
    # second run: should skip (run_one not called again)
    with patch.object(autopilot, "run_one", return_value=out) as ro2:
        autopilot.run_queue(q, allow_shutdown=False)
        assert ro2.call_count == 0
    # --force re-runs
    with patch.object(autopilot, "run_one", return_value=out) as ro3:
        autopilot.run_queue(q, force=True, allow_shutdown=False)
        assert ro3.call_count == 1


def test_run_queue_render_failure_continues(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{"topic": "boom"}, {"topic": "ok"}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one",
                      side_effect=[RuntimeError("render died"), out]):
        failures = autopilot.run_queue(q, allow_shutdown=False)
    assert failures == 1
    state = json.loads((tmp_path / "autopilot_state.json").read_text())
    statuses = sorted(r["status"] for r in state["done"].values())
    assert statuses == ["done", "failed"]


def test_run_queue_multiclip_path(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{
        "topic": "multi", "source_url": "https://yt/x",
        "multiclip_enabled": True, "multiclip_count": 2}])
    outs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for o in outs:
        o.write_bytes(b"x")
    with patch.object(autopilot, "run_multiclip", return_value=outs) as rm, \
         patch.object(autopilot, "run_one") as ro:
        autopilot.run_queue(q, allow_shutdown=False)
    assert rm.call_count == 1 and ro.call_count == 0


def test_run_queue_invokes_upload_when_enabled(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{
        "topic": "up", "upload": {"enabled": True, "privacy": "private"}}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one", return_value=out), \
         patch.object(autopilot, "upload_to_youtube", return_value="VID123") as up:
        autopilot.run_queue(q, allow_shutdown=False)
    assert up.call_count == 1
    state = json.loads((tmp_path / "autopilot_state.json").read_text())
    rec = list(state["done"].values())[0]
    assert rec["uploads"] == ["VID123"]


def test_run_queue_no_upload_flag(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{"topic": "up", "upload": {"enabled": True}}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one", return_value=out), \
         patch.object(autopilot, "upload_to_youtube") as up:
        autopilot.run_queue(q, do_upload=False, allow_shutdown=False)
    assert up.call_count == 0


def test_upload_failure_does_not_fail_job(tmp_path, fake_cfg_load):
    q = _write_queue(tmp_path, [{"topic": "up", "upload": {"enabled": True}}])
    out = tmp_path / "v.mp4"; out.write_bytes(b"x")
    with patch.object(autopilot, "run_one", return_value=out), \
         patch.object(autopilot, "upload_to_youtube",
                      side_effect=RuntimeError("no token")):
        failures = autopilot.run_queue(q, allow_shutdown=False)
    assert failures == 0  # render succeeded; upload error is non-fatal
    state = json.loads((tmp_path / "autopilot_state.json").read_text())
    rec = list(state["done"].values())[0]
    assert rec["status"] == "done" and rec.get("upload_errors")


def test_main_missing_file(tmp_path):
    rc = autopilot.main([str(tmp_path / "nope.json")])
    assert rc == 2
