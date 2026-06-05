"""WhisperX word-level caption alignment: gap-filler + dispatcher fallback.

The actual WhisperX run needs torch + GPU + model downloads (not available in
CI), so these tests cover the pure logic: timing gap-filling and the
dispatcher's fallback-to-faster-whisper behavior (both mocked).

Run: `pytest tests/test_whisperx.py -v`
"""

from unittest.mock import patch

import pipeline


# ── _fill_word_gaps ──────────────────────────────────────────────────────
class TestFillWordGaps:
    def test_all_timed_passthrough(self):
        raw = [[0.0, 0.4, "der"], [0.5, 0.9, "reichste"], [1.0, 1.4, "spieler"]]
        out = pipeline._fill_word_gaps(raw)
        assert out == [(0.0, 0.4, "der"), (0.5, 0.9, "reichste"),
                       (1.0, 1.4, "spieler")]

    def test_empty(self):
        assert pipeline._fill_word_gaps([]) == []

    def test_drops_blank_words(self):
        raw = [[0.0, 0.4, "hallo"], [0.5, 0.6, "   "], [0.7, 0.9, "welt"]]
        out = pipeline._fill_word_gaps(raw)
        assert [w for (_, _, w) in out] == ["hallo", "welt"]

    def test_interpolates_missing_middle_word(self):
        # "100" often comes back without alignment timing.
        raw = [[0.0, 0.4, "über"], [None, None, "100"], [1.0, 1.4, "Robux"]]
        out = pipeline._fill_word_gaps(raw)
        assert len(out) == 3
        s, e, w = out[1]
        assert w == "100"
        # Borrows prev end as start, next start as end.
        assert s == 0.4 and e == 1.0
        # No None leaks, monotonic-ish, start <= end everywhere.
        for s, e, _ in out:
            assert s is not None and e is not None
            assert s <= e

    def test_leading_and_trailing_gaps(self):
        raw = [[None, None, "ähm"], [0.5, 0.9, "ja"], [None, None, "okay"]]
        out = pipeline._fill_word_gaps(raw)
        assert len(out) == 3
        for s, e, _ in out:
            assert s is not None and e is not None
            assert s <= e

    def test_end_before_start_is_clamped(self):
        raw = [[1.0, 0.5, "kaputt"]]
        out = pipeline._fill_word_gaps(raw)
        s, e, _ = out[0]
        assert e >= s


# ── transcribe_words_best dispatcher ─────────────────────────────────────
class TestDispatcher:
    def test_off_uses_plain_faster_whisper(self):
        with patch.object(pipeline, "transcribe_words_subprocess",
                          return_value=([(0.0, 0.4, "x")], "cuda")) as plain, \
             patch.object(pipeline, "transcribe_words_whisperx_subprocess") as wx:
            words, dev = pipeline.transcribe_words_best(
                "a.wav", "small", use_whisperx=False)
        assert words == [(0.0, 0.4, "x")] and dev == "cuda"
        plain.assert_called_once()
        wx.assert_not_called()

    def test_on_uses_whisperx(self):
        with patch.object(pipeline, "transcribe_words_whisperx_subprocess",
                          return_value=([(0.0, 0.4, "y")], "cuda")) as wx, \
             patch.object(pipeline, "transcribe_words_subprocess") as plain:
            words, dev = pipeline.transcribe_words_best(
                "a.wav", "small", use_whisperx=True, language="de")
        assert words == [(0.0, 0.4, "y")]
        wx.assert_called_once()
        plain.assert_not_called()

    def test_whisperx_failure_falls_back(self):
        with patch.object(pipeline, "transcribe_words_whisperx_subprocess",
                          side_effect=RuntimeError("no whisperx")) as wx, \
             patch.object(pipeline, "transcribe_words_subprocess",
                          return_value=([(0.0, 0.4, "z")], "cpu")) as plain:
            words, dev = pipeline.transcribe_words_best(
                "a.wav", "small", use_whisperx=True)
        assert words == [(0.0, 0.4, "z")] and dev == "cpu"
        wx.assert_called_once()
        plain.assert_called_once()


# ── Config wiring ────────────────────────────────────────────────────────
import json
from pathlib import Path


def _write_cfg(tmp_path, **extra):
    data = {"output_dir": str(tmp_path / "out")}
    data.update(extra)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return pipeline.Config.load(p)


def test_config_defaults_whisperx_off(tmp_path):
    assert _write_cfg(tmp_path).use_whisperx is False


def test_config_reads_whisperx_flag(tmp_path):
    assert _write_cfg(tmp_path, use_whisperx=True).use_whisperx is True
