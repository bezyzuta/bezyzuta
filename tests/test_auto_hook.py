"""Auto-Hook: LLM writes a punchy hook overlay from the actual script.

The LLM call is mocked (no network), so these cover the parsing/cleaning and
the fallback chain.

Run: `pytest tests/test_auto_hook.py -v`
"""

from unittest.mock import patch

import pipeline


class _Cfg:
    use_claude_cli = False
    gemini_api_key = "AIza_fake"
    claude_cli_model = "sonnet"


# ── _clean_hook_line ─────────────────────────────────────────────────────
class TestCleanHookLine:
    def test_plain_line(self):
        assert pipeline._clean_hook_line("Er verlor alles in 3 Sekunden") == \
            "Er verlor alles in 3 Sekunden"

    def test_strips_quotes_and_period(self):
        assert pipeline._clean_hook_line('"Das hätte keiner gedacht."') == \
            "Das hätte keiner gedacht"

    def test_strips_code_fence_and_bullets(self):
        assert pipeline._clean_hook_line("```\n- POV: du bist pleite\n```") == \
            "POV: du bist pleite"

    def test_first_valid_line_wins(self):
        # A leading blank/too-long line is skipped for the first usable one.
        text = "\n" + ("x" * 80) + "\nNiemals aufgeben!"
        assert pipeline._clean_hook_line(text) == "Niemals aufgeben!"

    def test_too_long_returns_empty(self):
        assert pipeline._clean_hook_line("x" * 200) == ""

    def test_empty(self):
        assert pipeline._clean_hook_line("") == ""


# ── generate_auto_hook ───────────────────────────────────────────────────
class TestGenerateAutoHook:
    def test_uses_llm_reply(self):
        with patch.object(pipeline, "_complete_text",
                          return_value="Er fand 1 Million Robux"):
            hook = pipeline.generate_auto_hook("Ein langes Skript ...", _Cfg(), "de")
        assert hook == "Er fand 1 Million Robux"

    def test_empty_script_returns_empty(self):
        with patch.object(pipeline, "_complete_text") as llm:
            assert pipeline.generate_auto_hook("   ", _Cfg(), "de") == ""
        llm.assert_not_called()

    def test_falls_back_to_variants_when_llm_blank(self):
        with patch.object(pipeline, "_complete_text", return_value=""), \
             patch.object(pipeline, "generate_hook_variants",
                          return_value=["99% schaffen das nicht"]) as gv:
            hook = pipeline.generate_auto_hook("Skript text hier", _Cfg(), "de")
        assert hook == "99% schaffen das nicht"
        gv.assert_called_once()

    def test_passes_script_into_prompt(self):
        seen = {}

        def _cap(prompt, cfg, **kw):
            seen["prompt"] = prompt
            return "Hook hier"

        with patch.object(pipeline, "_complete_text", side_effect=_cap):
            pipeline.generate_auto_hook("MEINSKRIPT inhalt", _Cfg(), "en")
        assert "MEINSKRIPT inhalt" in seen["prompt"]

    def test_never_raises_returns_empty_on_total_failure(self):
        with patch.object(pipeline, "_complete_text",
                          side_effect=RuntimeError("down")), \
             patch.object(pipeline, "generate_hook_variants",
                          side_effect=RuntimeError("down too")):
            assert pipeline.generate_auto_hook("text", _Cfg(), "de") == ""
