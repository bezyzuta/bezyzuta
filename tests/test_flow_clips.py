"""Google Flow integration: export packaging (pipeline.write_flow_export),
clip matching, motion prompts, and the export/assemble wiring (run_one mocked).
No ffmpeg/render here — write_flow_export only copies files + writes JSON."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import pipeline
import flow_clips


# ── motion prompt ────────────────────────────────────────────────────────────
def test_motion_prompt_uses_motif_and_aspect():
    p = pipeline._flow_motion_prompt({"motif": "a lonely Roblox avatar in fog"}, "16:9")
    assert "a lonely Roblox avatar in fog" in p
    assert "16:9" in p
    assert "image-to-video" in p.lower()


def test_motion_prompt_falls_back_to_prompt_field():
    p = pipeline._flow_motion_prompt({"prompt": "dark hallway"}, "9:16")
    assert "dark hallway" in p and "9:16" in p


# ── write_flow_export packaging ──────────────────────────────────────────────
class _Cfg:
    target_w = 1920
    target_h = 1080
    tts_language = "de"
    image_style = "ms_paint_stickman"


def _make_imgs(tmp_path, n):
    imgs = []
    for i in range(n):
        p = tmp_path / f"image_{i+1}.png"
        p.write_bytes(b"\x89PNG" + bytes(20))
        imgs.append(p)
    return imgs


def test_write_flow_export_packages_everything(tmp_path):
    imgs = _make_imgs(tmp_path, 3)
    plan = [{"motif": "scene one"}, {"motif": "scene two"}, {"motif": "scene three"}]
    voice = tmp_path / "voice.mp3"; voice.write_bytes(b"id3" + bytes(50))
    export = tmp_path / "out_export"
    job = {"images_continuous": True, "image_change_secs": 3.0,
           "_flow_config_path": "config.json", "tts_language": "de",
           "flow_export_dir": str(export), "topic": "T"}

    out = pipeline.write_flow_export(export, "myslug", imgs, plan, voice, 30.0,
                                     job, _Cfg(), on_step=lambda m: None)
    assert out == export
    # files written
    assert (export / "voice.mp3").is_file()
    assert (export / "prompts.txt").is_file()
    assert (export / "beats.json").is_file()
    assert (export / "README.txt").is_file()
    for i in (1, 2, 3):
        assert (export / f"beat_{i:02d}.png").is_file()
    # prompts: one per beat
    prompts = (export / "prompts.txt").read_text(encoding="utf-8").splitlines()
    assert len(prompts) == 3 and "scene two" in prompts[1]
    # manifest structure
    man = json.loads((export / "beats.json").read_text(encoding="utf-8"))
    assert man["slug"] == "myslug" and man["n_beats"] == 3
    assert man["aspect"] == "16:9" and man["voice"] == "voice.mp3"
    assert man["tts_language"] == "de"
    assert len(man["beats"]) == 3
    assert man["beats"][0]["image"] == "beat_01.png"
    # job snapshot must NOT carry the export-only keys
    assert "flow_export_dir" not in man["job"]


def test_write_flow_export_no_voice_ok(tmp_path):
    imgs = _make_imgs(tmp_path, 1)
    export = tmp_path / "e"
    out = pipeline.write_flow_export(export, "s", imgs, [{"motif": "x"}],
                                     Path(tmp_path / "missing.mp3"), 10.0,
                                     {"topic": "t"}, _Cfg(), on_step=lambda m: None)
    man = json.loads((out / "beats.json").read_text(encoding="utf-8"))
    assert man["voice"] == ""  # voice missing → empty, still packages images


# ── clip matching ────────────────────────────────────────────────────────────
def test_match_clips_natural_sort(tmp_path):
    for n in (1, 2, 10):
        (tmp_path / f"clip_{n}.mp4").write_bytes(b"x")
    clips = flow_clips.match_clips(tmp_path, 3, on_step=lambda m: None)
    assert [c.name for c in clips] == ["clip_1.mp4", "clip_2.mp4", "clip_10.mp4"]


def test_match_clips_empty_raises(tmp_path):
    with pytest.raises(RuntimeError, match="keine Video-Clips"):
        flow_clips.match_clips(tmp_path, 0)


def test_match_clips_count_mismatch_warns_not_raises(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    msgs = []
    clips = flow_clips.match_clips(tmp_path, 5, on_step=msgs.append)
    assert len(clips) == 1
    assert any("erwartet" in m for m in msgs)


# ── export / assemble wiring (run_one mocked) ────────────────────────────────
def test_export_for_flow_sets_hook_and_calls_run_one(tmp_path):
    entry = {"topic": "Horror", "output_format": "faceless", "tts_language": "de",
             "config": "config.json", "flow_export_dir": str(tmp_path / "exp")}
    captured = {}

    def fake_run_one(job, cfg, on_step=None):
        captured["job"] = job
        captured["cfg"] = cfg
        return Path(job["flow_export_dir"])

    with patch.object(flow_clips.autopilot.Config, "load", return_value=_Cfg()), \
         patch.object(flow_clips, "run_one", side_effect=fake_run_one):
        out = flow_clips.export_for_flow(entry, on_step=lambda m: None)
    assert out == tmp_path / "exp"
    assert captured["job"]["flow_export_dir"] == str(tmp_path / "exp")
    assert captured["job"]["_flow_config_path"] == "config.json"
    # faceless → landscape geometry
    assert (captured["cfg"].target_w, captured["cfg"].target_h) == (1920, 1080)


def test_assemble_from_flow_feeds_clips_and_voice(tmp_path):
    export = tmp_path / "exp"; export.mkdir()
    (export / "voice.mp3").write_bytes(b"x")
    for n in (1, 2):
        (tmp_path / f"c{n}.mp4").write_bytes(b"x")
    manifest = {
        "slug": "s", "voice": "voice.mp3", "n_beats": 2,
        "target_w": 1920, "target_h": 1080, "config_path": "config.json",
        "tts_language": "de", "image_style": "ms_paint_stickman",
        "job": {"topic": "T", "caption_position": "bottom",
                "flow_export_dir": "should-be-removed"},
    }
    (export / "beats.json").write_text(json.dumps(manifest), encoding="utf-8")

    captured = {}

    def fake_run_one(job, cfg, on_step=None):
        captured["job"] = job; captured["cfg"] = cfg
        return Path("/out/s.mp4")

    with patch.object(flow_clips.Config, "load", return_value=_Cfg()), \
         patch.object(flow_clips, "run_one", side_effect=fake_run_one):
        out = flow_clips.assemble_from_flow(export, tmp_path, on_step=lambda m: None)
    assert out == Path("/out/s.mp4")
    job = captured["job"]
    assert len(job["image_paths"]) == 2                      # clips as beats
    assert job["voice_path"].endswith("voice.mp3")           # reuse export voice
    assert job["images_continuous"] is True
    assert "flow_export_dir" not in job                      # cleaned up
    assert captured["cfg"].target_w == 1920
