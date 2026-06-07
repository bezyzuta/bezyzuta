"""Caption-Polish: per-word karaoke highlight inside a readable chunk.

Run: `pytest tests/test_caption_polish.py -v`
"""

import pipeline


HL = "&H00FFFF&"  # ASS yellow (the active-word highlight color)


def _dialogues(text):
    return [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]


class TestCaptionPolish:
    def test_one_dialogue_per_word_in_chunk(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_polish=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # 3 words in one chunk -> 3 slices, each highlighting a different word.
        assert len(d) == 3

    def test_each_slice_shows_full_chunk_and_highlights_one_word(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_polish=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        for ln in d:
            # All three words present in every slice (chunk stays readable)…
            assert "DER" in ln and "REICHSTE" in ln and "SPIELER" in ln
            # …and exactly one highlight override present.
            assert ln.count(HL) == 1

    def test_highlight_walks_across_words(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out, caption_polish=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # The highlighted token differs per slice: the override block (which
        # ends with \b1}) wraps DER, then REICHSTE, then SPIELER.
        assert "\\b1}DER" in d[0]
        assert "\\b1}REICHSTE" in d[1]
        assert "\\b1}SPIELER" in d[2]

    def test_takes_precedence_over_word_karaoke(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out,
                           caption_polish=True, word_karaoke=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # Polish keeps the whole chunk on screen (multiple words per line);
        # word_karaoke would emit single-word lines. Multi-word => polish won.
        assert all(" " in ln.split(",,")[-1] for ln in d)

    def test_long_form_ignores_polish(self, tmp_path):
        # 8-word readable subtitle chunk; long_form must NOT do per-word polish.
        words = [(i * 0.5, i * 0.5 + 0.4, f"wort{i}") for i in range(8)]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1920, 1080, out,
                           caption_polish=True, long_form=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # One subtitle line for the whole 8-word phrase, no yellow highlight.
        assert len(d) == 1
        assert HL not in d[0]

    def test_emoji_line_still_added(self, tmp_path):
        words = [(0.0, 0.4, "viel"), (0.5, 0.9, "geld"), (1.0, 1.4, "robux")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out,
                           caption_polish=True, caption_emojis=True)
        text = out.read_text(encoding="utf-8")
        assert "\\N💰" in text

    def test_off_by_default_uses_plain_chunks(self, tmp_path):
        words = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1080, 1920, out)  # no caption_polish
        d = _dialogues(out.read_text(encoding="utf-8"))
        # Plain mode: one dialogue for the whole 3-word chunk, no highlight.
        assert len(d) == 1
        assert HL not in d[0]
