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
    def test_derive_includes_cinematic_style(self):
        p = pipeline.derive_image_prompt("a rich roblox player with a crown")
        assert "cinematic 3D render" in p
        assert "a rich roblox player with a crown" in p
        # No leftover flat-cartoon style from the old prompt.
        assert "vertical cartoon illustration" not in p
        assert "blocky aesthetic" not in p

    def test_finalize_appends_style_to_motif(self):
        out = pipeline._finalize_scene_prompt("a fire demon avatar")
        assert "a fire demon avatar" in out
        assert pipeline._IMAGE_STYLE_SUFFIX in out

    def test_finalize_no_double_suffix(self):
        # A prompt that already has the suffix (e.g. the base fallback) must
        # not get it twice.
        already = pipeline.derive_image_prompt("x")
        out = pipeline._finalize_scene_prompt(already)
        assert out.count("cinematic 3D render") == 1

    def test_finalize_strips_whitespace(self):
        assert pipeline._finalize_scene_prompt("  motif  ").startswith("motif,")

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
