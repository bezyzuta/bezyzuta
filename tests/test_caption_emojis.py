"""Expanded contextual caption-emoji map: coverage + a few new mappings."""

import pipeline


def test_every_category_emoji_has_a_code_entry():
    # Stable cache filenames rely on the code map (ord() fallback aside).
    for _kw, emoji in pipeline._CAPTION_EMOJI_KEYWORDS:
        assert emoji in pipeline._EMOJI_TWEMOJI_CODE, f"no code for {emoji}"


def test_more_categories_than_before():
    # The map was expanded for more coverage/variety; guard against regressions.
    assert len(pipeline._CAPTION_EMOJI_KEYWORDS) >= 30


def test_new_horror_and_emotion_mappings():
    cases = {
        "er ist gestorben": "💀",
        "überall blut": "🩸",
        "ein gruseliger geist": "👻",
        "das war eine lüge": "🤥",
        "schau genau hin": "👀",
        "sie weinen tränen": "😭",
        "er war so wütend": "😡",
        "gesperrte tür": "🔒",
        "komplett gratis": "🎁",
    }
    for text, emoji in cases.items():
        assert pipeline._emoji_for_caption(text) == emoji, text


def test_no_match_stays_clean():
    assert pipeline._emoji_for_caption("ein ganz normaler satz ohne treffer") == ""
