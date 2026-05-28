"""Tests for the long-form additions in youtube_optimizer:
   - timestamp formatting
   - instruction-template picker (short vs long, portrait vs landscape)
   - chapter generator's short-circuit + post-processing rules
No network calls — chapter generation against Gemini is only smoke-tested
via the no-key short-circuit path.
"""

import json
from unittest.mock import patch

import pytest

import youtube_optimizer as yo


class TestFormatTimestamp:
    @pytest.mark.parametrize("seconds,expected", [
        (0,    "0:00"),
        (5,    "0:05"),
        (60,   "1:00"),
        (90,   "1:30"),
        (599,  "9:59"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (7325, "2:02:05"),
    ])
    def test_format(self, seconds, expected):
        assert yo._format_chapter_timestamp(seconds) == expected

    def test_negative_floors_to_zero(self):
        assert yo._format_chapter_timestamp(-5) == "0:00"

    def test_float_input_truncates(self):
        assert yo._format_chapter_timestamp(90.7) == "1:30"


class TestPickInstructions:
    def test_short_video_uses_shorts_prompt(self):
        assert yo._pick_instructions(30, "portrait") == yo._PROMPT_INSTRUCTIONS
        assert yo._pick_instructions(60, "landscape") == yo._PROMPT_INSTRUCTIONS

    def test_long_portrait(self):
        assert yo._pick_instructions(300, "portrait") == yo._PROMPT_INSTRUCTIONS_LONG_PORTRAIT
        # boundary
        assert yo._pick_instructions(90, "portrait") == yo._PROMPT_INSTRUCTIONS_LONG_PORTRAIT

    def test_long_landscape(self):
        assert yo._pick_instructions(300, "landscape") == yo._PROMPT_INSTRUCTIONS_LONG_LANDSCAPE
        assert yo._pick_instructions(90, "LANDSCAPE") == yo._PROMPT_INSTRUCTIONS_LONG_LANDSCAPE


class _FakeCfgNoKey:
    gemini_api_key = ""
    gemini_model = "gemini-2.5-flash"


class _FakeCfgWithKey:
    gemini_api_key = "AIza_fake"
    gemini_model = "gemini-2.5-flash"


class TestGenerateChaptersShortCircuits:
    def test_no_gemini_key(self):
        assert yo.generate_chapters("Bro look at this", 300.0, _FakeCfgNoKey()) == ""

    def test_short_video_returns_empty(self):
        # < 90s → no chapters even with key
        assert yo.generate_chapters("Bro look at this", 30.0, _FakeCfgWithKey()) == ""

    def test_empty_script(self):
        assert yo.generate_chapters("", 300.0, _FakeCfgWithKey()) == ""
        assert yo.generate_chapters("   ", 300.0, _FakeCfgWithKey()) == ""


def _mock_gemini_response(chapter_list):
    """Build a Gemini API response shape with the chapter JSON in the text part."""
    return {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps(chapter_list)}]}
        }]
    }


class TestGenerateChaptersPostProcessing:
    """The post-processing logic (enforce 0:00 first, >=10s gaps, etc.) is
    the tricky bit — mock Gemini and verify the output respects YouTube's
    chapter rules regardless of what the model returns."""

    def test_normal_chapters_emit(self):
        chapters = [
            {"title": "Intro", "position": 0.0},
            {"title": "First obstacle", "position": 0.2},
            {"title": "The trap", "position": 0.5},
            {"title": "Final moment", "position": 0.85},
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy script", 300.0, _FakeCfgWithKey())
        # Must start at 0:00 and be ascending
        lines = out.strip().split("\n")
        assert lines[0].startswith("0:00 Intro")
        assert "1:00" in lines[1]   # 0.2 * 300 = 60s
        assert "2:30" in lines[2]   # 0.5 * 300 = 150s
        assert "4:15" in lines[3]   # 0.85 * 300 = 255s

    def test_first_chapter_forced_to_zero(self):
        """YouTube refuses chapter blocks where the first timestamp isn't
        0:00. Even if Gemini gives the first chapter a non-zero position,
        we clamp it."""
        chapters = [
            {"title": "Intro", "position": 0.05},  # 15s into a 300s video
            {"title": "Middle", "position": 0.4},
            {"title": "End", "position": 0.9},
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        assert out.startswith("0:00 Intro")

    def test_drops_chapters_closer_than_10s(self):
        """YouTube rejects the whole block if any two consecutive chapters
        are less than 10s apart. Drop the offenders."""
        chapters = [
            {"title": "Intro", "position": 0.0},
            {"title": "TooClose", "position": 0.01},   # 3s into 300s
            {"title": "Real second", "position": 0.2},  # 60s
            {"title": "Third", "position": 0.5},        # 150s
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        assert "TooClose" not in out
        assert "Real second" in out

    def test_too_few_chapters_returns_empty(self):
        # YouTube needs ≥3 chapters. After dedup we'd have <3 → drop the
        # whole block rather than emit something invalid.
        chapters = [
            {"title": "Only one", "position": 0.0},
            {"title": "Second", "position": 0.5},
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        assert out == ""

    def test_malformed_json_returns_empty(self):
        """Gemini sometimes wraps JSON in ```json ... ``` or emits prose.
        Should silently fall through, not crash."""
        bad = {"candidates": [{"content": {"parts": [{"text": "Sorry I can't do that"}]}}]}
        with patch("pipeline._gemini_post", return_value=bad):
            assert yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey()) == ""

    def test_markdown_wrapped_json_parses(self):
        """Gemini often replies with ```json\\n[...]\\n``` despite "no markdown"."""
        chapters = [
            {"title": "Intro", "position": 0.0},
            {"title": "Mid", "position": 0.4},
            {"title": "End", "position": 0.85},
        ]
        wrapped_text = "```json\n" + json.dumps(chapters) + "\n```"
        resp = {"candidates": [{"content": {"parts": [{"text": wrapped_text}]}}]}
        with patch("pipeline._gemini_post", return_value=resp):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        assert out.startswith("0:00 Intro")
        assert "End" in out

    def test_invalid_position_entries_skipped(self):
        chapters = [
            {"title": "Intro", "position": 0.0},
            {"title": "Bad", "position": "not a number"},     # type error
            {"title": "Out of range", "position": 1.5},       # >1.0
            {"title": "Missing position"},                    # KeyError
            {"title": "Middle", "position": 0.4},
            {"title": "End", "position": 0.85},
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        # The 3 valid ones survive
        lines = out.strip().split("\n")
        assert len(lines) == 3
        assert "Bad" not in out
        assert "Out of range" not in out

    def test_chapters_get_sorted_by_position(self):
        # Gemini sometimes returns out-of-order. We sort.
        chapters = [
            {"title": "End", "position": 0.85},
            {"title": "Intro", "position": 0.0},
            {"title": "Middle", "position": 0.4},
        ]
        with patch("pipeline._gemini_post", return_value=_mock_gemini_response(chapters)):
            out = yo.generate_chapters("dummy", 300.0, _FakeCfgWithKey())
        lines = out.strip().split("\n")
        assert lines[0].endswith("Intro")
        assert lines[1].endswith("Middle")
        assert lines[2].endswith("End")
