"""Tests for the music-snippet generator. ffmpeg/whisper/image-gen are mocked
(none run in CI), so these cover the pure logic and the orchestration:
window filtering, song resolution, the image-provider fallback, and that
run_music_snippet renders N clips and survives a per-clip failure."""

import types
from pathlib import Path
from unittest import mock

import music_snippet as M


# ───────────────────────── lyrics window ─────────────────────────

class TestLyricsWindow:
    def test_filters_and_rebases_to_zero(self):
        words = [(0, 1, "a"), (2, 3, "b"), (14, 15, "c"), (16, 17, "d")]
        win = M._lyrics_window(words, 14.0, 15.0)   # window 14..29
        assert win == [(0.0, 1.0, "c"), (2.0, 3.0, "d")]

    def test_clips_words_overhanging_the_edges(self):
        win = M._lyrics_window([(13, 16, "x")], 14.0, 15.0)  # 13..16 → 0..2
        assert win == [(0.0, 2.0, "x")]

    def test_drops_words_outside_window(self):
        assert M._lyrics_window([(0, 1, "a"), (40, 41, "z")], 14.0, 15.0) == []

    def test_empty_words(self):
        assert M._lyrics_window([], 0.0, 15.0) == []


# ───────────────────────── song resolution ─────────────────────────

class TestResolveSong:
    def test_explicit_song_path_wins(self, tmp_path):
        f = tmp_path / "song.mp3"; f.write_bytes(b"x" * 100)
        got = M._resolve_song({"song_path": str(f)}, cfg=types.SimpleNamespace())
        assert got == f

    def test_falls_back_to_music_dir_pick(self, tmp_path):
        with mock.patch.object(M.P, "pick_music_track", return_value=tmp_path / "a.mp3"):
            got = M._resolve_song({"music_dir": str(tmp_path), "music_track": ""},
                                  cfg=types.SimpleNamespace())
        assert got.name == "a.mp3"

    def test_raises_when_no_song(self):
        with mock.patch.object(M.P, "pick_music_track", return_value=None):
            try:
                M._resolve_song({}, cfg=types.SimpleNamespace())
                assert False, "should raise"
            except RuntimeError:
                pass


# ───────────────────────── image provider fallback ─────────────────────────

class TestGenerateDarkImage:
    def test_grok_first_when_enabled(self, tmp_path):
        cfg = types.SimpleNamespace(use_grok_cli=True)
        out = tmp_path / "i.png"
        with mock.patch.object(M.P, "fetch_image_from_grok_cli") as g:
            assert M._generate_dark_image("scene", out, cfg) is True
            g.assert_called_once()
            # dark-aesthetic suffix appended to the prompt
            assert "black and white" in g.call_args[0][0] or "desaturated" in g.call_args[0][0]

    def test_falls_back_to_pollinations(self, tmp_path):
        cfg = types.SimpleNamespace(use_grok_cli=False, cloudflare_account_id="",
                                    cloudflare_api_token="")
        out = tmp_path / "i.png"
        with mock.patch.object(M.P, "fetch_image_from_pollinations") as poll, \
             mock.patch.object(M.P, "_faceless_recrop"):
            assert M._generate_dark_image("scene", out, cfg) is True
            poll.assert_called_once()

    def test_returns_false_when_all_fail(self, tmp_path):
        cfg = types.SimpleNamespace(use_grok_cli=False, cloudflare_account_id="",
                                    cloudflare_api_token="")
        out = tmp_path / "i.png"
        with mock.patch.object(M.P, "fetch_image_from_pollinations",
                               side_effect=RuntimeError("down")):
            assert M._generate_dark_image("scene", out, cfg) is False


# ───────────────────────── orchestration ─────────────────────────

def _cfg(tmp_path):
    return types.SimpleNamespace(
        output_dir=str(tmp_path), target_w=1080, target_h=1920,
        whisper_model="base", use_whisperx=False, whisperx_python="",
        use_grok_cli=False, cloudflare_account_id="", cloudflare_api_token="")


class TestRunMusicSnippet:
    def test_renders_n_clips(self, tmp_path):
        song = tmp_path / "song.mp3"; song.write_bytes(b"x" * 100)
        job = {"slug": "track", "song_path": str(song), "snippet_count": 3,
               "snippet_duration": 15.0, "topic": "moody city", "snippet_lyrics": True}
        cfg = _cfg(tmp_path)
        rendered = []
        with mock.patch.object(M.P, "_media_duration", return_value=120.0), \
             mock.patch.object(M.P, "transcribe_words_best",
                               return_value=([(1, 2, "hello"), (3, 4, "world")], "cuda")), \
             mock.patch.object(M, "_generate_dark_image", return_value=True), \
             mock.patch.object(M.P, "write_ass"), \
             mock.patch.object(M, "_render_snippet",
                               side_effect=lambda *a, **k: rendered.append(a[5])):
            outs = M.run_music_snippet(job, cfg)
        assert len(outs) == 3
        assert all(p.name.startswith("track_snippet_") for p in outs)

    def test_skips_clip_when_image_fails(self, tmp_path):
        song = tmp_path / "song.mp3"; song.write_bytes(b"x" * 100)
        job = {"slug": "t", "song_path": str(song), "snippet_count": 3,
               "snippet_duration": 15.0, "topic": "x", "snippet_lyrics": False}
        cfg = _cfg(tmp_path)
        # image fails for clip 2 only
        calls = {"n": 0}
        def img(*a, **k):
            calls["n"] += 1
            return calls["n"] != 2
        with mock.patch.object(M.P, "_media_duration", return_value=120.0), \
             mock.patch.object(M, "_generate_dark_image", side_effect=img), \
             mock.patch.object(M.P, "write_ass"), \
             mock.patch.object(M, "_render_snippet"):
            outs = M.run_music_snippet(job, cfg)
        assert len(outs) == 2   # clip 2 skipped, run continued

    def test_continues_when_one_render_fails(self, tmp_path):
        song = tmp_path / "song.mp3"; song.write_bytes(b"x" * 100)
        job = {"slug": "t", "song_path": str(song), "snippet_count": 2,
               "snippet_duration": 15.0, "topic": "x", "snippet_lyrics": False}
        cfg = _cfg(tmp_path)
        calls = {"n": 0}
        def render(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("ffmpeg boom")
        with mock.patch.object(M.P, "_media_duration", return_value=120.0), \
             mock.patch.object(M, "_generate_dark_image", return_value=True), \
             mock.patch.object(M.P, "write_ass"), \
             mock.patch.object(M, "_render_snippet", side_effect=render):
            outs = M.run_music_snippet(job, cfg)
        assert len(outs) == 1   # first failed, second succeeded
