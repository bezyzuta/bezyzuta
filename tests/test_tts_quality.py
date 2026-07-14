"""Tests for the TTS text-normalization upgrades: abbreviation/symbol
spell-out and decimal number reading."""

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
