"""The short-form script prompts enforce a curiosity-gap structure (open loop
-> escalate -> payoff withheld to the end -> CTA), which is the biggest
retention lever. Guard against a silent revert to the old hook/action/CTA list.
"""

import pipeline


def test_de_short_prompt_has_curiosity_gap():
    p = pipeline.SCRIPT_PROMPT_SHORT.lower()
    assert "curiosity gap" in p
    assert "noch nicht" in p          # don't reveal the answer yet
    assert "letzten" in p              # payoff in the LAST seconds
    # still keeps the length placeholders intact
    assert "{target_low}" in pipeline.SCRIPT_PROMPT_SHORT
    assert "{words_high}" in pipeline.SCRIPT_PROMPT_SHORT


def test_en_short_prompt_has_curiosity_gap():
    p = pipeline.SCRIPT_PROMPT_SHORT_EN.lower()
    assert "curiosity gap" in p
    assert "do not reveal" in p
    assert "final" in p                # payoff in the FINAL seconds
    assert "{target_low}" in pipeline.SCRIPT_PROMPT_SHORT_EN


def test_short_prompts_still_format_cleanly():
    # The placeholders must still .format() without KeyError.
    for tpl in (pipeline.SCRIPT_PROMPT_SHORT, pipeline.SCRIPT_PROMPT_SHORT_EN):
        out = tpl.format(topic="x", target_low=20, target_high=30,
                         words_low=50, words_high=80)
        assert "curiosity" in out.lower()
