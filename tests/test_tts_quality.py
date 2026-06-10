"""Tests for the German TTS clarity upgrades: abbreviation/symbol spell-out,
decimal number reading, the Whisper-QA similarity scoring, and the
German-specific Chatterbox knobs in Config."""

import json
from pathlib import Path

import pipeline as p


# ───────────────────────── abbreviations & symbols ─────────────────────────

class TestSpellAbbreviations:
    def test_german_abbreviations(self):
        out = p._spell_abbreviations_for_tts(
            "Das ist z.B. wichtig, d.h. ca. die Hälfte, usw.", "de")
        assert "zum Beispiel" in out
        assert "das heißt" in out
        assert "circa" in out
        assert "und so weiter" in out

    def test_german_symbols(self):
        out = p._spell_abbreviations_for_tts("50% Rabatt und 3 Mio. Gewinn", "de")
        assert "50 Prozent" in out
        assert "Millionen" in out

    def test_currency_symbol_moved_behind_number(self):
        # '€50' must become '50 Euro', not 'Euro fünfzig'.
        out = p._spell_abbreviations_for_tts("Das kostet €50 heute", "de")
        assert "50 Euro" in out
        out = p._spell_abbreviations_for_tts("That's $20 right there", "en")
        assert "20 dollars" in out

    def test_ampersand_only_freestanding(self):
        out = p._spell_abbreviations_for_tts("Tom & Jerry", "de")
        assert " und " in out
        # No && inside words: AT&T style strings keep their symbol.
        out2 = p._spell_abbreviations_for_tts("AT&T bleibt", "de")
        assert "AT&T" in out2

    def test_english_minimal_set(self):
        out = p._spell_abbreviations_for_tts("e.g. 50% etc.", "en")
        assert "for example" in out
        assert "percent" in out
        assert "et cetera" in out

    def test_plain_text_untouched(self):
        text = "Ganz normaler Satz ohne irgendwas."
        assert p._spell_abbreviations_for_tts(text, "de") == text


# ───────────────────────── decimal numbers ─────────────────────────

class TestDecimalNumbers:
    def test_german_decimal_comma(self):
        out = p._spell_numbers_for_tts("3,5 Millionen", "de")
        assert "drei Komma fünf" in out

    def test_german_thousands_dot_still_integer(self):
        out = p._spell_numbers_for_tts("1.000 Spieler", "de")
        assert "eintausend" in out
        assert "Komma" not in out

    def test_english_decimal_point(self):
        out = p._spell_numbers_for_tts("3.5 million", "en")
        assert "three point five" in out

    def test_year_reading_unchanged(self):
        out = p._spell_numbers_for_tts("im Jahr 1979", "de")
        assert "neunzehnhundertneunundsiebzig" in out

    def test_combined_pipeline_order(self):
        # Same order as synthesize_voiceover: abbreviations first, then numbers.
        text = p._spell_abbreviations_for_tts("z.B. 3,5% Bonus", "de")
        text = p._spell_numbers_for_tts(text, "de")
        assert text == "zum Beispiel drei Komma fünf Prozent Bonus"


# ───────────────────────── QA similarity scoring ─────────────────────────

class TestQaSimilarity:
    def test_identical_ignoring_case_punctuation(self):
        score = p._tts_chunk_similarity(
            "Bro, schau dir DAS an!", "bro schau dir das an")
        assert score > 0.95

    def test_mumbled_words_score_low(self):
        score = p._tts_chunk_similarity(
            "Bro, schau dir das an!", "bro war irgendwas raus")
        assert score < 0.82

    def test_empty_expected_is_perfect(self):
        assert p._tts_chunk_similarity("", "whatever") == 1.0

    def test_umlauts_survive_normalization(self):
        assert p._tts_norm_words("Schöne Grüße, läuft!") == [
            "schöne", "grüße", "läuft"]


# ───────────────────────── config wiring ─────────────────────────

class TestGermanTtsConfig:
    def test_example_config_defaults(self):
        cfg = p.Config.load(Path(__file__).parent.parent / "config.example.json")
        assert cfg.tts_exaggeration_de == 0.4
        assert cfg.tts_cfg_weight_de == 0.65
        assert cfg.tts_qa_retries == 2

    def test_defaults_when_keys_missing(self, tmp_path):
        minimal = dict(json.loads(
            (Path(__file__).parent.parent / "config.example.json").read_text(
                encoding="utf-8")))
        for k in ("tts_exaggeration_de", "tts_cfg_weight_de", "tts_qa_retries"):
            minimal.pop(k, None)
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(minimal), encoding="utf-8")
        cfg = p.Config.load(cfg_file)
        assert cfg.tts_exaggeration_de == 0.4
        assert cfg.tts_cfg_weight_de == 0.65
        assert cfg.tts_qa_retries == 2

    def test_validate_flags_out_of_range_de_knobs(self, tmp_path):
        data = dict(json.loads(
            (Path(__file__).parent.parent / "config.example.json").read_text(
                encoding="utf-8")))
        data["tts_cfg_weight_de"] = 1.7
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(data), encoding="utf-8")
        cfg = p.Config.load(cfg_file)
        _errors, warnings = cfg.validate()
        assert any("tts_cfg_weight_de" in w for w in warnings)

    def test_german_chunk_limit_smaller(self):
        assert p._CHATTERBOX_MAX_CHARS_DE < p._CHATTERBOX_MAX_CHARS
