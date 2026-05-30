"""Tests for the KI-directed effects engine: generate_effect_plan (timing)
and _effects_final_vf (the ffmpeg filter chain it produces)."""

import json
from unittest.mock import patch

import pytest

import pipeline


class _Cfg:
    use_claude_cli = False
    gemini_api_key = "AIza_fake"
    gemini_model = "gemini-2.5-flash"


class _CfgNoLLM:
    use_claude_cli = False
    gemini_api_key = ""
    gemini_model = "x"


class TestEffectPlan:
    def test_nothing_enabled(self):
        plan = pipeline.generate_effect_plan("s", 30.0, [], _Cfg())
        assert plan["color_grade"] is False
        assert plan["flashes"] == [] and plan["shakes"] == []

    def test_color_grade_is_global_flag(self):
        plan = pipeline.generate_effect_plan("s", 30.0, ["color_grade"], _Cfg(),
                                             ai_direction=False)
        assert plan["color_grade"] is True
        # no timed effects requested
        assert not plan["flashes"] and not plan["shakes"]

    def test_no_llm_even_distribution(self):
        plan = pipeline.generate_effect_plan("s", 32.0, ["flash", "shake"],
                                             _CfgNoLLM(), ai_direction=False)
        assert plan["flashes"] or plan["shakes"]
        # shakes are (start,end) windows
        for s, e in plan["shakes"]:
            assert e > s

    def test_llm_places_beats(self):
        payload = '[{"position":0.1,"type":"flash"},{"position":0.5,"type":"shake"},{"position":0.9,"type":"flash"}]'
        with patch("pipeline._complete_text", return_value=payload):
            plan = pipeline.generate_effect_plan("script", 100.0,
                                                 ["flash", "shake"], _Cfg(), ai_direction=True)
        assert 10.0 in plan["flashes"] and 90.0 in plan["flashes"]
        assert any(abs(s - 50.0) < 0.01 for s, e in plan["shakes"])

    def test_llm_respects_allowed_only(self):
        # shake requested by LLM but only flash is enabled → shake dropped
        payload = '[{"position":0.3,"type":"shake"},{"position":0.6,"type":"flash"}]'
        with patch("pipeline._complete_text", return_value=payload):
            plan = pipeline.generate_effect_plan("script", 100.0,
                                                 ["flash"], _Cfg(), ai_direction=True)
        assert plan["shakes"] == []
        assert 60.0 in plan["flashes"]

    def test_llm_failure_falls_back(self):
        with patch("pipeline._complete_text", side_effect=RuntimeError("boom")):
            plan = pipeline.generate_effect_plan("script", 40.0,
                                                 ["flash"], _Cfg(), ai_direction=True)
        # fell back to even distribution → still some flashes
        assert plan["flashes"]

    def test_markdown_fenced_json(self):
        payload = '```json\n[{"position":0.2,"type":"flash"}]\n```'
        with patch("pipeline._complete_text", return_value=payload):
            plan = pipeline.generate_effect_plan("script", 50.0, ["flash"], _Cfg())
        assert 10.0 in plan["flashes"]


class TestEffectsVf:
    def test_empty_when_none(self):
        assert pipeline._effects_final_vf(None, 1080, 1920) == ""
        assert pipeline._effects_final_vf({}, 1080, 1920) == ""

    def test_color_grade_filters(self):
        vf = pipeline._effects_final_vf({"color_grade": True}, 1080, 1920)
        assert "eq=" in vf and "vignette" in vf

    def test_flash_drawbox(self):
        vf = pipeline._effects_final_vf({"flashes": [1.0, 2.5]}, 1080, 1920)
        assert "drawbox" in vf and "between(t" in vf

    def test_shake_crop_scale(self):
        vf = pipeline._effects_final_vf({"shakes": [(1.0, 1.4)]}, 1080, 1920)
        assert "crop=" in vf and "scale=1080:1920" in vf

    def test_all_combined(self):
        vf = pipeline._effects_final_vf(
            {"color_grade": True, "flashes": [1.0], "shakes": [(2.0, 2.4)]}, 1080, 1920)
        # order: shake (crop) → eq → drawbox
        assert vf.index("crop=") < vf.index("eq=") < vf.index("drawbox")

    def test_punch_zoom(self):
        vf = pipeline._effects_final_vf({"punches": [1.0, 2.0]}, 1080, 1920)
        assert "iw/(1+0.12" in vf and "scale=1080:1920" in vf


class TestEffectPlanBatch2:
    def test_global_flags(self):
        plan = pipeline.generate_effect_plan(
            "s", 30.0, ["ken_burns", "slide_in"], _Cfg(), ai_direction=False)
        assert plan["ken_burns"] is True and plan["slide_in"] is True

    def test_punch_is_timed(self):
        payload = '[{"position":0.5,"type":"punch"}]'
        with patch("pipeline._complete_text", return_value=payload):
            plan = pipeline.generate_effect_plan("script", 100.0, ["punch"], _Cfg())
        assert 50.0 in plan["punches"]

    def test_ken_burns_in_image_chain(self):
        on = pipeline._image_chain(2, 0, 3.0, 0.0, 800, 0.0, ken_burns=True)
        off = pipeline._image_chain(2, 0, 3.0, 0.0, 800, 0.0, ken_burns=False)
        assert "0.06*(t/" in on        # drifting width
        assert "0.06*(t/" not in off
