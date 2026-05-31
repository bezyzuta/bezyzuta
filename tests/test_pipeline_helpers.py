"""Pure-Python helpers in pipeline.py — no GPU, no network, no ML deps.

Run: `pytest tests/test_pipeline_helpers.py -v`
"""

from unittest.mock import patch

import pytest

import pipeline


class _Cfg:
    use_claude_cli = False
    gemini_api_key = "AIza_fake"
    gemini_model = "gemini-2.5-flash"


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


# ─────────────────────── long-form script extension ───────────────────────


class TestExtendScriptToTarget:
    """The bounded-chunk top-up loop. A real LLM under-delivers per call
    (ignores 'write 900 more words'), so a single big request only recovered
    ~half the deficit (600s asked → ~340s). The loop must keep going."""

    def _chunked(self, words_per_call=200):
        """Mimic an LLM that returns a fixed ~N words no matter what's asked."""
        def _cont(previous, cfg, add_words, language="de", on_step=None):
            return "wort " * words_per_call
        return _cont

    def test_loops_until_near_target(self):
        # 300w start, target 600s @ 2.4 wps. The estimate pass is a rough
        # pre-size (chunk-boundary rounding), so accept ~85%+ of target words;
        # the exact length is corrected later by _grow_voiceover_to_target.
        start = "wort " * 300
        with patch("pipeline._gemini_continuation", side_effect=self._chunked(200)):
            out = pipeline._extend_script_to_target(start, _Cfg(), 600.0, "de")
        words = len(out.split())
        assert words >= int(600 * 2.4 * 0.85), f"only reached {words}w"

    def test_single_call_would_be_too_short(self):
        # Sanity: ONE 200-word top-up on a 300w script is nowhere near 1440w —
        # this is the bug we're fixing, proven by the loop test above clearing it.
        start = "wort " * 300
        one = (start.rstrip() + " " + ("wort " * 200)).split()
        assert len(one) < int(1440 * 0.92)

    def test_stalls_out_without_infinite_loop(self):
        # LLM returns nothing → stop after two empty rounds, keep what we have.
        def _empty(previous, cfg, add_words, language="de", on_step=None):
            return ""
        with patch("pipeline._gemini_continuation", side_effect=_empty):
            out = pipeline._extend_script_to_target("wort " * 300, _Cfg(), 600.0, "de")
        assert len(out.split()) == 300

    def test_stops_when_continuation_raises(self):
        with patch("pipeline._gemini_continuation", side_effect=RuntimeError("api down")):
            out = pipeline._extend_script_to_target("wort " * 300, _Cfg(), 600.0, "de")
        assert len(out.split()) == 300  # original kept, no crash

    def test_already_long_enough_is_noop(self):
        long_script = "wort " * 1500  # already > 1440w target
        with patch("pipeline._gemini_continuation", side_effect=AssertionError("should not be called")):
            out = pipeline._extend_script_to_target(long_script, _Cfg(), 600.0, "de")
        assert len(out.split()) == 1500

    def test_chunk_request_is_bounded(self):
        # Each call must request at most _CONTINUATION_CHUNK_WORDS, never the
        # whole deficit (which the LLM would ignore).
        seen = []
        def _spy(previous, cfg, add_words, language="de", on_step=None):
            seen.append(add_words)
            return "wort " * 200
        with patch("pipeline._gemini_continuation", side_effect=_spy):
            pipeline._extend_script_to_target("wort " * 300, _Cfg(), 600.0, "de")
        assert seen and max(seen) <= pipeline._CONTINUATION_CHUNK_WORDS


class TestGrowVoiceoverToTarget:
    """The post-TTS feedback loop: extend using the MEASURED spoken duration,
    not a wps guess. This is what actually makes a 600s request hit ~600s."""

    def _patches(self, real_wps):
        """Patch the TTS/audio helpers so each synthesized chunk's duration is
        words / real_wps. Mirrors a real voice that speaks at real_wps."""
        from unittest.mock import patch as _p

        def fake_synth(text, cfg, out):
            self._durs[str(out)] = len(text.split()) / real_wps
            return out

        def fake_trim(inp, out, **kw):
            self._durs[str(out)] = self._durs.get(str(inp), 0.0)
            return out

        def fake_probe(p):
            return self._durs.get(str(p), 0.0)

        def fake_concat(parts, out):
            self._durs[str(out)] = sum(self._durs.get(str(p), 0.0) for p in parts)
            return out

        return [
            _p("pipeline.synthesize_voiceover", side_effect=fake_synth),
            _p("pipeline.trim_leading_silence", side_effect=fake_trim),
            _p("pipeline.probe_duration", side_effect=fake_probe),
            _p("pipeline._concat_audio", side_effect=fake_concat),
        ]

    def test_grows_fast_voice_to_target(self, tmp_path):
        # Voice speaks 4.5 w/s. Initial 1586w script → ~352s. Target 600s.
        self._durs = {}
        real_wps = 4.5
        script = "wort " * 1586
        vo = tmp_path / "voice.mp3"
        self._durs[str(vo)] = 1586 / real_wps  # ~352s

        def cont(previous, cfg, add_words, language="de", on_step=None):
            return "wort " * min(add_words, pipeline._CONTINUATION_CHUNK_WORDS)

        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._patches(real_wps):
                stack.enter_context(p)
            stack.enter_context(patch("pipeline._gemini_continuation", side_effect=cont))
            new_vo, new_dur, new_script = pipeline._grow_voiceover_to_target(
                script, vo, 1586 / real_wps, _Cfg(), 600.0, "en", tmp_path)
        assert new_dur >= 600 * 0.92, f"only reached {new_dur:.0f}s"
        assert len(new_script.split()) > 1586

    def test_noop_when_already_long(self, tmp_path):
        self._durs = {}
        vo = tmp_path / "voice.mp3"
        with patch("pipeline._gemini_continuation",
                   side_effect=AssertionError("should not extend")):
            new_vo, new_dur, new_script = pipeline._grow_voiceover_to_target(
                "wort " * 1500, vo, 590.0, _Cfg(), 600.0, "en", tmp_path)
        assert new_dur == 590.0 and new_vo == vo

    def test_noop_for_short_targets(self, tmp_path):
        vo = tmp_path / "voice.mp3"
        with patch("pipeline._gemini_continuation",
                   side_effect=AssertionError("should not run for <90s")):
            new_vo, new_dur, _ = pipeline._grow_voiceover_to_target(
                "wort " * 50, vo, 20.0, _Cfg(), 30.0, "en", tmp_path)
        assert new_dur == 20.0

    def test_noop_without_backend(self, tmp_path):
        class NoBackend:
            use_claude_cli = False
            gemini_api_key = ""
        vo = tmp_path / "voice.mp3"
        new_vo, new_dur, _ = pipeline._grow_voiceover_to_target(
            "wort " * 100, vo, 100.0, NoBackend(), 600.0, "en", tmp_path)
        assert new_dur == 100.0 and new_vo == vo
