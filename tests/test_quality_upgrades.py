"""Tests for the reference-matching quality upgrades:
   - cinematic image prompt style + beat-matched scene prompts
   - contextual caption emojis
   - straight-vs-tilted image option (via write_ass/compose plumbing)
   - loudness normalization wiring
The image-style and emoji logic is pure and fully testable here; the
ffmpeg-touching bits (normalize_loudness, compose tilt) are checked at the
signature/plumbing level since they need real media.
"""

import inspect

import pytest

import pipeline


class TestCinematicImagePrompts:
    def test_derive_includes_quality_suffix(self):
        p = pipeline.derive_image_prompt("a rich roblox player with a crown")
        assert pipeline._IMAGE_STYLE_SUFFIX in p
        assert "a rich roblox player with a crown" in p
        # No leftover flat-cartoon style from the old prompt.
        assert "vertical cartoon illustration" not in p
        assert "blocky aesthetic" not in p

    def test_derive_default_is_style_neutral(self):
        # With image_style=auto (no cfg), the suffix must NOT force a medium —
        # no hard-coded "Roblox" in the appended style.
        p = pipeline.derive_image_prompt("a shocked person")
        assert "Roblox" not in pipeline._IMAGE_STYLE_SUFFIX
        assert "Roblox" not in p

    def test_finalize_appends_style_to_motif(self):
        out = pipeline._finalize_scene_prompt("a fire demon avatar")
        assert "a fire demon avatar" in out
        assert pipeline._IMAGE_STYLE_SUFFIX in out

    def test_finalize_no_double_suffix(self):
        # A prompt that already has the suffix (e.g. the base fallback) must
        # not get it twice.
        already = pipeline.derive_image_prompt("x")
        out = pipeline._finalize_scene_prompt(already)
        assert out.count(pipeline._IMAGE_STYLE_SUFFIX) == 1

    def test_finalize_strips_whitespace(self):
        assert pipeline._finalize_scene_prompt("  motif  ").startswith("motif,")

    def test_image_style_roblox_preset_forces_roblox(self):
        class _C:
            image_style = "roblox"
        out = pipeline._finalize_scene_prompt("a guy with a crown", _C())
        assert "Roblox blocky avatar" in out

    def test_image_style_realistic_preset(self):
        class _C:
            image_style = "realistic"
        out = pipeline.derive_image_prompt("a city at night", _C())
        assert "photorealistic" in out
        assert "Roblox" not in out

    def test_image_style_custom_verbatim(self):
        class _C:
            image_style = "anime watercolor"
        out = pipeline._finalize_scene_prompt("a hero", _C())
        assert "anime watercolor" in out

    def test_faceless_stickman_uses_flat_suffix(self):
        # The MS-Paint preset must NOT carry the cinematic suffix (rim lighting,
        # saturated colors, depth of field) — that would fight the flat look.
        class _C:
            image_style = "ms_paint_stickman"
        out = pipeline.derive_image_prompt("a person in an empty room", _C())
        assert "MS Paint" in out and "stickman" in out
        assert "dramatic rim lighting" not in out
        assert "vibrant saturated colors" not in out
        assert "depth of field" not in out
        assert "no watermark" in out  # minimal flat suffix still applied

    def test_faceless_doodle_uses_flat_suffix(self):
        class _C:
            image_style = "doodle_sketch"
        out = pipeline._finalize_scene_prompt("a person thinking", _C())
        assert "doodle" in out or "sketch" in out
        assert "dramatic rim lighting" not in out

    def test_faceless_styles_force_zero_roblox(self):
        for style in ("ms_paint_stickman", "doodle_sketch"):
            class _C:
                image_style = style
                image_roblox_max = 5
            assert pipeline._roblox_cap(_C()) == 0

    def test_scene_prompt_template_asks_for_motif_only(self):
        # The template must instruct beat-matching and motif-only output.
        assert "ILLUSTRIEREN" in pipeline.SCENE_PROMPT
        assert "{n}" in pipeline.SCENE_PROMPT
        assert "{script}" in pipeline.SCENE_PROMPT


class TestCaptionEmojis:
    @pytest.mark.parametrize("text,expected", [
        ("du wirst der reichste spieler", "💰"),
        ("ACHTUNG das ist gefährlich", "⚠️"),
        ("das ist so krass und wahnsinn", "😱"),
        ("ein gruseliger creepy moment", "😨"),
        ("der mächtige boss erscheint", "🔥"),
        ("schick das video deinem freund", "🤝"),
        ("warum passiert das eigentlich", "🤔"),
        ("just a normal english sentence here", ""),
        ("ganz normaler satz ohne treffer", ""),
    ])
    def test_emoji_matching(self, text, expected):
        assert pipeline._emoji_for_caption(text) == expected

    def test_first_match_wins(self):
        # "geld" (money) is listed before "achtung" — money wins if both.
        assert pipeline._emoji_for_caption("achtung viel geld") == "💰"

    def test_case_insensitive(self):
        assert pipeline._emoji_for_caption("GELD GELD GELD") == "💰"

    def test_write_ass_adds_emoji_line_when_enabled(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_emojis=True)
        text = out.read_text(encoding="utf-8")
        # Emoji on its own line (ASS hard newline \N) below the caption.
        assert "\\N💰" in text

    def test_write_ass_no_emoji_when_disabled(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_emojis=False)
        text = out.read_text(encoding="utf-8")
        assert "💰" not in text

    def test_write_ass_no_emoji_when_no_keyword(self, tmp_path):
        words = [(0.0, 0.4, "und"), (0.5, 0.9, "dann"), (1.0, 1.4, "weiter")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_emojis=True)
        text = out.read_text(encoding="utf-8")
        # No trigger word → clean caption, no stray \N emoji.
        assert "\\N" not in text.split("Dialogue:")[-1]


class TestVoiceClonePrep:
    def test_prepares_clean_mono_capped_sample(self, tmp_path):
        import subprocess, wave
        rec = tmp_path / "rec.wav"
        # 20s tone with 3s of leading silence — should come out mono/24k,
        # silence-trimmed, capped to <=12s.
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=200:duration=20",
             "-af", "volume=0:enable='lt(t,3)'", str(rec)],
            check=True, capture_output=True,
        )
        out = pipeline.prepare_voice_sample(rec, tmp_path / "rec.clone.wav")
        assert out.is_file()
        with wave.open(str(out)) as w:
            assert w.getnchannels() == 1
            assert w.getframerate() == 24000
            assert w.getnframes() / w.getframerate() <= 12.5

    def test_prepare_signature_default_maxsecs(self):
        sig = inspect.signature(pipeline.prepare_voice_sample)
        assert sig.parameters["max_secs"].default == 12.0


class TestPlumbing:
    def test_normalize_loudness_exists(self):
        assert callable(pipeline.normalize_loudness)
        sig = inspect.signature(pipeline.normalize_loudness)
        assert "target_lufs" in sig.parameters
        assert sig.parameters["target_lufs"].default == -14.0

    def test_compose_short_has_image_tilt(self):
        sig = inspect.signature(pipeline.compose_short)
        assert "image_tilt" in sig.parameters
        assert sig.parameters["image_tilt"].default is True

    def test_write_ass_has_caption_emojis(self):
        sig = inspect.signature(pipeline.write_ass)
        assert "caption_emojis" in sig.parameters
        assert sig.parameters["caption_emojis"].default is False


def _ass_pop_style(text: str) -> str:
    return [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]


class TestCaptionPosition:
    def test_top_uses_alignment_8(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass([(0.0, 0.4, "hi")], 1080, 1920, out, caption_position="top")
        cols = [c.strip() for c in _ass_pop_style(out.read_text()).split(",")]
        # Alignment is the 5th-from-last field (…align, MarginL, MarginR, MarginV, Encoding)
        assert cols[-5] == "8"

    def test_bottom_uses_alignment_2(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass([(0.0, 0.4, "hi")], 1080, 1920, out, caption_position="bottom")
        cols = [c.strip() for c in _ass_pop_style(out.read_text()).split(",")]
        assert cols[-5] == "2"

    def test_center_uses_alignment_5(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass([(0.0, 0.4, "hi")], 1080, 1920, out, caption_position="center")
        cols = [c.strip() for c in _ass_pop_style(out.read_text()).split(",")]
        assert cols[-5] == "5"

    def test_longform_forces_bottom(self, tmp_path):
        # Even when "top" is requested, landscape long-form stays at bottom.
        out = tmp_path / "c.ass"
        pipeline.write_ass([(0.0, 0.4, "hi")], 1920, 1080, out,
                           caption_position="top", long_form=True)
        cols = [c.strip() for c in _ass_pop_style(out.read_text()).split(",")]
        assert cols[-5] == "2"


class TestEmojiOverlay:
    def test_emoji_overlay_suppresses_text_emoji(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(
            [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")],
            1080, 1920, out, caption_emojis=True, emoji_overlay=True,
        )
        # Color PNG overlay handles it instead → no monochrome emoji in ASS.
        assert "💰" not in out.read_text()

    def test_text_emoji_present_without_overlay(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(
            [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")],
            1080, 1920, out, caption_emojis=True, emoji_overlay=False,
        )
        assert "💰" in out.read_text()

    def test_codepoint_map_known_emojis(self):
        assert pipeline._EMOJI_TWEMOJI_CODE["💰"] == "1f4b0"
        assert pipeline._EMOJI_TWEMOJI_CODE["⚠️"] == "26a0"  # FE0F stripped

    def test_get_emoji_png_none_without_color_font(self, tmp_path, monkeypatch):
        # No color-emoji font on the machine → return None so the caller
        # falls back to the monochrome ASS-text emoji. Use a clean cache
        # dir so a previously-rendered PNG can't short-circuit the check.
        monkeypatch.setattr(pipeline, "_EMOJI_CACHE_DIR", tmp_path / "emoji")
        monkeypatch.setattr(pipeline, "_EMOJI_FONT_CACHE", None)
        monkeypatch.setattr(pipeline, "_find_emoji_font", lambda override="": None)
        assert pipeline.get_emoji_png("💰") is None

    def test_get_emoji_png_renders_color_when_font_present(self, tmp_path, monkeypatch):
        # If this machine has a color emoji font, get_emoji_png returns a
        # real RGBA PNG; otherwise the feature degrades to None (text
        # fallback). Either outcome is acceptable — assert the contract.
        monkeypatch.setattr(pipeline, "_EMOJI_CACHE_DIR", tmp_path / "emoji")
        monkeypatch.setattr(pipeline, "_EMOJI_FONT_CACHE", None)
        font = pipeline._find_emoji_font()
        out = pipeline.get_emoji_png("💰")
        if font is None:
            assert out is None
        else:
            assert out is not None and out.is_file()
            from PIL import Image
            im = Image.open(out)
            assert im.mode == "RGBA"

    def test_find_emoji_font_override_missing(self):
        assert pipeline._find_emoji_font("/no/such/font.ttf") is None

    def test_compute_emoji_events_timing(self):
        # Three 3-word chunks; only the money one triggers.
        words = [
            (0.0, 0.4, "und"), (0.5, 0.9, "dann"), (1.0, 1.4, "passiert"),
            (2.0, 2.4, "viel"), (2.5, 2.9, "geld"), (3.0, 3.4, "kommt"),
        ]
        events = pipeline.compute_caption_emoji_events(words)
        assert len(events) == 1
        s, e, emo, text = events[0]
        assert emo == "💰"
        assert s == 2.0 and e == 3.4
        assert "geld" in text


class TestContinuousImages:
    def test_continuous_starts_on_beat(self):
        # Each image starts exactly on its beat (i * slice), so it lines up
        # with the narration; first image at t=0.
        sched = pipeline._image_schedule(4, 30.0, 1.5, continuous=True, gap=0.5)
        slice_dur = 30.0 / 4
        assert sched[0][0] == 0.0
        for i, (start, _end) in enumerate(sched):
            assert abs(start - i * slice_dur) < 0.01

    def test_continuous_leaves_gap_between_images(self):
        gap = 0.5
        sched = pipeline._image_schedule(5, 30.0, 1.5, continuous=True, gap=gap)
        for i in range(1, len(sched)):
            # the gameplay-only gap between image i-1 end and image i start
            assert abs(sched[i][0] - sched[i - 1][1] - gap) < 0.01

    def test_continuous_gap_zero_is_seamless(self):
        sched = pipeline._image_schedule(5, 30.0, 1.5, continuous=True, gap=0.0)
        for i in range(1, len(sched)):
            assert abs(sched[i][0] - sched[i - 1][1]) < 0.01

    def test_continuous_short_slice_keeps_image_visible(self):
        # Many images on a short video → gap would eat the slice; keep the
        # image visible instead of producing zero/negative duration.
        sched = pipeline._image_schedule(20, 12.0, 1.5, continuous=True, gap=0.5)
        assert all(e > s for s, e in sched)

    def test_non_continuous_unchanged(self):
        # Default behavior (gaps) must be untouched.
        sched = pipeline._image_schedule(3, 30.0, 1.5)
        assert len(sched) == 3
        assert all(abs((e - s) - 1.5) < 0.01 for s, e in sched)

    def test_compose_short_has_new_params(self):
        sig = inspect.signature(pipeline.compose_short)
        assert "images_continuous" in sig.parameters
        assert "emoji_events" in sig.parameters
        assert "caption_position" in sig.parameters
