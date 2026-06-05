"""Caption-Highlight-Box and Wort-für-Wort-Aufbau (build-up) caption styles.

Run: `pytest tests/test_caption_box_buildup.py -v`
"""

import pipeline


HL = "&H00FFFF&"  # yellow used by both the box border and the buildup highlight


def _dialogues(text):
    return [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]


WORDS = [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"), (1.0, 1.4, "spieler")]


class TestCaptionBox:
    def test_active_word_gets_yellow_box(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out, caption_box=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert len(d) == 3  # one slice per word
        for ln in d:
            # Black text + thick yellow border = the box look.
            assert "\\1c&H000000&" in ln and "\\3c" + HL in ln and "\\bord7" in ln
            # Whole chunk stays visible (static, like polish).
            assert "DER" in ln and "REICHSTE" in ln and "SPIELER" in ln

    def test_box_highlight_walks(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out, caption_box=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert "\\b1}DER" in d[0]
        assert "\\b1}REICHSTE" in d[1]
        assert "\\b1}SPIELER" in d[2]


class TestCaptionBuildup:
    def test_line_grows_word_by_word(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out, caption_buildup=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert len(d) == 3
        # Slice 1 shows only the first word, slice 2 two words, slice 3 all three.
        assert "REICHSTE" not in d[0] and "DER" in d[0]
        assert "DER" in d[1] and "REICHSTE" in d[1] and "SPIELER" not in d[1]
        assert "DER" in d[2] and "REICHSTE" in d[2] and "SPIELER" in d[2]

    def test_newest_word_is_highlighted(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out, caption_buildup=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert "\\b1}DER" in d[0]
        assert "\\b1}REICHSTE" in d[1]
        assert "\\b1}SPIELER" in d[2]

    def test_buildup_with_box_combines(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out,
                           caption_buildup=True, caption_box=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # Build-up reveal (grows) AND box styling (black text + yellow border).
        assert "SPIELER" not in d[0]
        assert "\\1c&H000000&" in d[0] and "\\bord7" in d[0]


class TestPrecedenceAndGuards:
    def test_takes_precedence_over_polish(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out,
                           caption_box=True, caption_polish=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        # Box wins: black-text box override present (polish never sets \1c black).
        assert any("\\1c&H000000&" in ln for ln in d)

    def test_long_form_ignores_both(self, tmp_path):
        words = [(i * 0.5, i * 0.5 + 0.4, f"wort{i}") for i in range(8)]
        out = tmp_path / "c.ass"
        pipeline.write_ass(words, 1920, 1080, out,
                           caption_box=True, caption_buildup=True, long_form=True)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert len(d) == 1
        assert "\\1c&H000000&" not in d[0]

    def test_off_by_default(self, tmp_path):
        out = tmp_path / "c.ass"
        pipeline.write_ass(WORDS, 1080, 1920, out)
        d = _dialogues(out.read_text(encoding="utf-8"))
        assert len(d) == 1  # plain single chunk
        assert "\\1c&H000000&" not in d[0]
