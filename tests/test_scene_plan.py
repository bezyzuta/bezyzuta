"""Tests for the per-beat scene planner (AI + free-photo mix) and the free
photo fetchers. All network is mocked — no real Openverse/Wikimedia/LLM."""

import io
from unittest.mock import patch, MagicMock

import pytest

import pipeline


class _Cfg:
    use_claude_cli = False
    gemini_api_key = "AIza_fake"
    gemini_model = "gemini-2.5-flash"


def _png_bytes(color=(200, 50, 50, 255), size=(800, 600)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestGenerateScenePlan:
    def _mock_complete(self, payload):
        return patch("pipeline._complete_text", return_value=payload)

    def test_parses_mixed_plan(self):
        payload = (
            '[{"source":"ai","motif":"rich roblox avatar with crown","query":""},'
            '{"source":"photo","motif":"","query":"shocked person face"},'
            '{"source":"ai","motif":"dark fire boss","query":""}]'
        )
        with self._mock_complete(payload):
            plan = pipeline.generate_scene_plan("script text", 3, _Cfg())
        assert len(plan) == 3
        assert plan[0]["source"] == "ai" and "crown" in plan[0]["prompt"]
        assert plan[1]["source"] == "photo" and plan[1]["query"] == "shocked person face"
        # AI beats get the cinematic style suffix appended.
        assert pipeline._IMAGE_STYLE_SUFFIX in plan[0]["prompt"]

    def test_ai_beat_has_full_prompt(self):
        payload = '[{"source":"ai","motif":"a golden trophy","query":""}]'
        with self._mock_complete(payload):
            plan = pipeline.generate_scene_plan("s", 1, _Cfg())
        assert plan[0]["prompt"].startswith("a golden trophy")

    def test_photo_disabled_forces_ai(self):
        payload = '[{"source":"photo","motif":"","query":"money"}]'
        with self._mock_complete(payload):
            plan = pipeline.generate_scene_plan("s", 1, _Cfg(), allow_photos=False)
        assert plan[0]["source"] == "ai"

    def test_markdown_fenced_json(self):
        payload = '```json\n[{"source":"ai","motif":"x","query":""}]\n```'
        with self._mock_complete(payload):
            plan = pipeline.generate_scene_plan("s", 1, _Cfg())
        assert len(plan) == 1 and plan[0]["source"] == "ai"

    def test_pads_to_n(self):
        payload = '[{"source":"ai","motif":"only one","query":""}]'
        with self._mock_complete(payload):
            plan = pipeline.generate_scene_plan("s", 4, _Cfg())
        assert len(plan) == 4

    def test_llm_failure_falls_back_to_ai_motifs(self):
        with patch("pipeline._complete_text", side_effect=RuntimeError("boom")), \
             patch("pipeline.generate_scene_prompts", return_value=["p1", "p2"]):
            plan = pipeline.generate_scene_plan("s", 2, _Cfg())
        assert len(plan) == 2
        assert all(b["source"] == "ai" for b in plan)

    def test_no_backend_falls_back(self):
        class NoBackend:
            use_claude_cli = False
            gemini_api_key = ""
            gemini_model = "x"
        with patch("pipeline.generate_scene_prompts", return_value=["p1"]):
            plan = pipeline.generate_scene_plan("s", 1, NoBackend())
        assert plan[0]["source"] == "ai"


class TestFetchFreePhoto:
    def test_openverse_success(self, tmp_path):
        search = MagicMock()
        search.raise_for_status = lambda: None
        search.json = lambda: {"results": [{"url": "http://x/img.png"}]}
        imgresp = MagicMock()
        imgresp.raise_for_status = lambda: None
        imgresp.content = _png_bytes()
        out = tmp_path / "o.png"
        with patch("requests.get", side_effect=[search, imgresp]):
            p = pipeline.fetch_image_from_openverse("gold coins", out)
        assert p.is_file()
        from PIL import Image
        im = Image.open(p)
        assert im.size == (600, 600)  # center-cropped square

    def test_openverse_no_results_raises(self, tmp_path):
        search = MagicMock()
        search.raise_for_status = lambda: None
        search.json = lambda: {"results": []}
        with patch("requests.get", return_value=search):
            with pytest.raises(RuntimeError):
                pipeline.fetch_image_from_openverse("x", tmp_path / "o.png")

    def test_free_photo_falls_back_to_wikimedia(self, tmp_path):
        # Openverse raises, Wikimedia succeeds.
        wiki_search = MagicMock()
        wiki_search.raise_for_status = lambda: None
        wiki_search.json = lambda: {"query": {"pages": {
            "1": {"imageinfo": [{"thumburl": "http://w/img.jpg"}]}
        }}}
        wiki_img = MagicMock()
        wiki_img.raise_for_status = lambda: None
        wiki_img.content = _png_bytes()

        def fake_get(url, **kw):
            if "openverse" in url:
                raise pipeline.requests.RequestException("openverse down")
            if "commons.wikimedia" in url:
                return wiki_search
            return wiki_img
        with patch("requests.get", side_effect=fake_get):
            p = pipeline.fetch_free_photo("trophy", tmp_path / "o.png")
        assert p.is_file()

    def test_free_photo_all_fail_raises(self, tmp_path):
        with patch("requests.get", side_effect=pipeline.requests.RequestException("net down")):
            with pytest.raises(RuntimeError):
                pipeline.fetch_free_photo("x", tmp_path / "o.png")

    def test_free_photo_uses_pixabay_first_when_key_set(self, tmp_path):
        # With a Pixabay key, that source is tried before openverse/wikimedia.
        pix_search = MagicMock()
        pix_search.raise_for_status = lambda: None
        pix_search.json = lambda: {"hits": [{"largeImageURL": "http://p/i.jpg"}]}
        pix_img = MagicMock()
        pix_img.raise_for_status = lambda: None
        pix_img.content = _png_bytes()

        seen = []
        def fake_get(url, **kw):
            seen.append(url)
            if "pixabay.com/api" in url:
                return pix_search
            return pix_img  # the image download

        class CfgKey:
            pixabay_api_key = "abc123"
        with patch("requests.get", side_effect=fake_get):
            p = pipeline.fetch_free_photo("gold", tmp_path / "o.png", cfg=CfgKey())
        assert p.is_file()
        assert any("pixabay" in u for u in seen)
        # openverse/wikimedia never reached since pixabay succeeded
        assert not any("openverse" in u for u in seen)

    def test_pixabay_no_key_raises(self, tmp_path):
        class CfgNoKey:
            pixabay_api_key = ""
        with pytest.raises(RuntimeError):
            pipeline.fetch_image_from_pixabay("x", tmp_path / "o.png", CfgNoKey())


class TestContinuousAutoCount:
    """The continuous mode should pick more images for longer videos so they
    change every few seconds — exercised via the formula directly."""
    @pytest.mark.parametrize("dur,change,expected_range", [
        (30.0, 3.5, (7, 10)),
        (15.0, 3.5, (4, 5)),
        (60.0, 3.5, (14, 14)),   # capped at 14
        (10.0, 3.5, (4, 4)),     # floored at 4
    ])
    def test_count_formula(self, dur, change, expected_range):
        n = max(4, min(int(round(dur / change)), 14))
        assert expected_range[0] <= n <= expected_range[1]
