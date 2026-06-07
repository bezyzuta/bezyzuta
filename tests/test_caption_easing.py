"""Caption pop animations use an ease-out accel for a satisfying snap."""

import pipeline


def _dialogues(text):
    return [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]


def test_pop_captions_use_eased_tween(tmp_path):
    words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
    out = tmp_path / "c.ass"
    pipeline.write_ass(words, 1080, 1920, out, pop_captions=True)
    text = out.read_text(encoding="utf-8")
    # Eased (accel<1) tween, not the old linear \t(0,150,\fscx100...).
    assert "\\t(0,150,0.6," in text
    assert "\\t(0,150,\\fscx100" not in text


def test_word_karaoke_uses_eased_tween(tmp_path):
    words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste")]
    out = tmp_path / "c.ass"
    pipeline.write_ass(words, 1080, 1920, out, word_karaoke=True)
    text = out.read_text(encoding="utf-8")
    assert "\\t(0,160,0.6," in text
