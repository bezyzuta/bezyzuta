"""write_ass caption styling — verifies the short (portrait/TikTok) path is
unchanged and the new long_form (landscape) path differs in the right ways.

words format matches what Whisper produces downstream: (start, end, text).
"""

import pytest

import pipeline


def _words(n: int):
    """n dummy timed words, 0.5s apart."""
    return [(i * 0.5, i * 0.5 + 0.4, f"word{i}") for i in range(n)]


def _read(tmp_path, **kwargs):
    out = tmp_path / "captions.ass"
    defaults = dict(
        words=_words(24),
        video_w=1080, video_h=1920,
        out_path=out,
    )
    defaults.update(kwargs)
    pipeline.write_ass(**defaults)
    return out.read_text(encoding="utf-8")


class TestShortFormUnchanged:
    """The user said shorts are perfect — lock the portrait behavior down so
    the long-form branch can't accidentally regress it."""

    def test_short_is_all_caps(self, tmp_path):
        text = _read(tmp_path, words=[(0.0, 0.4, "hello"), (0.5, 0.9, "world"), (1.0, 1.4, "bro")])
        assert "HELLO WORLD BRO" in text

    def test_short_uses_3_word_chunks(self, tmp_path):
        # 6 words → 2 dialogue lines of 3 words each.
        text = _read(tmp_path, words=_words(6))
        dialogue_pop = [l for l in text.splitlines() if l.startswith("Dialogue:") and ",Pop,," in l]
        assert len(dialogue_pop) == 2

    def test_short_margin_is_360(self, tmp_path):
        text = _read(tmp_path)
        pop_style = [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]
        assert pop_style.rstrip().endswith("360, 1")

    def test_short_pop_animation_present_when_enabled(self, tmp_path):
        text = _read(tmp_path, pop_captions=True)
        assert "\\fscx125\\fscy125" in text

    def test_short_default_font_size(self, tmp_path):
        # 1920 * 0.048 = 92
        text = _read(tmp_path, video_w=1080, video_h=1920)
        pop_style = [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]
        # "Style: Pop, Impact, 92, ..."
        assert pop_style.split(",")[2].strip() == "92"


class TestLongFormCaptions:
    def test_long_form_keeps_original_case(self, tmp_path):
        text = _read(
            tmp_path, video_w=1920, video_h=1080, long_form=True,
            words=[(0.0, 0.4, "Hello"), (0.5, 0.9, "World"), (1.0, 1.4, "bro")],
        )
        assert "Hello World bro" in text
        assert "HELLO WORLD BRO" not in text

    def test_long_form_uses_8_word_chunks(self, tmp_path):
        # 16 words → 2 dialogue lines of 8 words each.
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=True, words=_words(16))
        dialogue_pop = [l for l in text.splitlines() if l.startswith("Dialogue:") and ",Pop,," in l]
        assert len(dialogue_pop) == 2

    def test_long_form_anchored_near_bottom(self, tmp_path):
        # 1080 * 0.06 = 64.8 → 64
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=True)
        pop_style = [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]
        margin_v = int(pop_style.split(",")[-2].strip())
        assert margin_v < 100  # near bottom, not the 360 shorts value
        assert margin_v == 64

    def test_long_form_no_pop_animation_even_if_requested(self, tmp_path):
        # pop_captions=True should be ignored in long-form.
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=True, pop_captions=True)
        assert "\\fscx125\\fscy125" not in text

    def test_long_form_smaller_relative_font(self, tmp_path):
        # 1080 * 0.045 = 48.6 → 48
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=True)
        pop_style = [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]
        assert pop_style.split(",")[2].strip() == "48"

    def test_explicit_font_size_respected_in_both_modes(self, tmp_path):
        for lf in (True, False):
            text = _read(tmp_path, video_w=1920, video_h=1080, long_form=lf, font_size=70)
            pop_style = [l for l in text.splitlines() if l.startswith("Style: Pop,")][0]
            assert pop_style.split(",")[2].strip() == "70"


class TestCaptionsCommon:
    """Behavior shared by both modes shouldn't change with long_form."""

    @pytest.mark.parametrize("long_form", [True, False])
    def test_hook_text_present(self, tmp_path, long_form):
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=long_form,
                     hook_text="WATCH THIS")
        assert ",Hook,," in text
        assert "WATCH THIS" in text

    @pytest.mark.parametrize("long_form", [True, False])
    def test_captions_disabled(self, tmp_path, long_form):
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=long_form,
                     enable_captions=False)
        assert ",Pop,," not in text

    @pytest.mark.parametrize("long_form", [True, False])
    def test_subscribe_overlay(self, tmp_path, long_form):
        text = _read(tmp_path, video_w=1920, video_h=1080, long_form=long_form,
                     subscribe_overlay=True, total_duration=60.0)
        assert ",Sub,," in text
