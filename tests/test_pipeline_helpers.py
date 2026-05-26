"""Pure-Python helpers in pipeline.py — no GPU, no network, no ML deps.

Run: `pytest tests/test_pipeline_helpers.py -v`
"""

import pytest

import pipeline


# ───────────────────────── language detection ─────────────────────────


class TestDetectLanguage:
    def test_empty_returns_en(self):
        assert pipeline._detect_language("") == "en"
        assert pipeline._detect_language("   ") == "en"

    def test_umlauts_force_german(self):
        # Any ä/ö/ü/ß is decisive — even one is enough.
        assert pipeline._detect_language("Hello über there") == "de"
        assert pipeline._detect_language("ä") == "de"

    def test_pure_english(self):
        assert pipeline._detect_language(
            "Look at this absolutely insane Roblox moment dude"
        ) == "en"

    def test_pure_german(self):
        assert pipeline._detect_language(
            "Bro, schau dir das an, das ist absolut der Wahnsinn"
        ) == "de"

    def test_german_no_umlauts_via_stopwords(self):
        # No umlauts — relies on stopword ratio >10%.
        assert pipeline._detect_language(
            "Du musst dir das anschauen, das ist krass!"
        ) == "de"

    def test_mostly_english_with_one_german_word(self):
        # Single "der" in long English text should NOT flip to German.
        text = "Look at the insane Roblox moment der dude pulled off here today"
        assert pipeline._detect_language(text) == "en"


# ───────────────────────── chatterbox chunking ─────────────────────────


class TestSplitSentencesForTTS:
    def test_empty(self):
        assert pipeline._split_sentences_for_tts("") == []
        assert pipeline._split_sentences_for_tts("   ") == []

    def test_short_text_single_chunk(self):
        result = pipeline._split_sentences_for_tts("Hello world.")
        assert result == ["Hello world."]

    def test_packs_sentences_greedily(self):
        # Three short sentences should pack into one chunk.
        result = pipeline._split_sentences_for_tts(
            "First. Second. Third.", max_chars=280
        )
        assert len(result) == 1
        assert "First" in result[0] and "Third" in result[0]

    def test_long_text_splits(self):
        text = ("Bro, das ist absolut wild. " * 30).strip()
        chunks = pipeline._split_sentences_for_tts(text, max_chars=200)
        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)

    def test_never_overflows_max_chars(self):
        # Hostile input: a single sentence longer than max_chars.
        # Should fall back to comma split, then to word split.
        text = "Bro, " + "absolut wild, " * 50 + "krass."
        chunks = pipeline._split_sentences_for_tts(text, max_chars=100)
        assert all(len(c) <= 100 for c in chunks), [len(c) for c in chunks]

    def test_no_sentence_boundary_no_commas(self):
        # Pathological: 200 words with no punctuation at all.
        text = "word " * 200
        chunks = pipeline._split_sentences_for_tts(text, max_chars=100)
        assert all(len(c) <= 100 for c in chunks)
        # No content should be lost.
        joined = " ".join(chunks).split()
        assert len(joined) == 200


# ───────────────────────── LLM-preamble stripper ─────────────────────────


class TestCleanUserScript:
    def test_empty(self):
        assert pipeline._clean_user_script("") == ""
        assert pipeline._clean_user_script("   ") == ""

    def test_no_preamble_unchanged(self):
        text = "Bro check this out!\n\nMore content here."
        assert pipeline._clean_user_script(text) == text

    def test_strips_real_user_failure_case(self):
        """Exact failure mode reported by the user: pasted ChatGPT output
        where the first line is the assistant's meta-intro."""
        text = (
            "Here is the high-energy English script for your 8-minute and "
            "30-second gameplay video about Escape the Barber Obby:\n\n"
            "Bro, get ready! This obby is INSANE!"
        )
        out = pipeline._clean_user_script(text)
        assert "Here is the high-energy" not in out
        assert out.startswith("Bro, get ready")

    @pytest.mark.parametrize("header", [
        "Here's a wild script for you:",
        "Sure! Here is the script you asked for:",
        "Absolutely! Below is the YouTube script for the gameplay:",
        "I've written a high-energy script for your video about obby:",
        "Hier ist das Skript fuer dein Roblox-Video:",
        "Klar, hier hast du das Skript:",
    ])
    def test_strips_known_preamble_variants(self, header):
        text = header + "\n\nBro schau dir das an!"
        out = pipeline._clean_user_script(text)
        assert header not in out
        assert "Bro" in out

    def test_keeps_legit_colon_content(self):
        # "Player one says: this is wild" ends with colon but is real
        # content, not a preamble. Must not be stripped.
        text = "Player one says: this is wild\n\nMore content"
        assert pipeline._clean_user_script(text) == text

    def test_keeps_short_first_line(self):
        # "Listen up:" is 10 chars — below the 20-char minimum.
        text = "Listen up:\n\nReal script content."
        assert pipeline._clean_user_script(text) == text

    def test_no_blank_line_separator(self):
        # If first line isn't followed by an empty line, it's probably
        # not a preamble — leave it alone.
        text = "Here is the script for you: bro look at this"
        assert pipeline._clean_user_script(text) == text


# ───────────────────────── script-length estimator ─────────────────────────


class TestEstimateScriptSeconds:
    def test_english_uses_2_5_wps(self):
        # 250 EN words ≈ 100 seconds (2.5 wps)
        secs = pipeline._estimate_script_seconds("word " * 250, "en")
        assert 95 < secs < 105

    def test_german_uses_2_4_wps(self):
        # 240 DE words ≈ 100 seconds (2.4 wps)
        secs = pipeline._estimate_script_seconds("wort " * 240, "de")
        assert 95 < secs < 105

    def test_empty(self):
        assert pipeline._estimate_script_seconds("", "de") == 0.0

    def test_unknown_language_defaults_to_de(self):
        # Robustness: unknown lang shouldn't crash, falls back to German wps.
        secs = pipeline._estimate_script_seconds("wort " * 240, "fr")
        assert 95 < secs < 105
