"""Dead-Air-Trim: remove long voiceover pauses, with a safety revert.

ffmpeg isn't available in CI, so `run` and `probe_duration` are mocked; these
cover the safety logic and the filter the function builds.

Run: `pytest tests/test_dead_air.py -v`
"""

from pathlib import Path
from unittest.mock import patch

import pipeline


def _paths(tmp_path):
    src = tmp_path / "voice.mp3"
    src.write_bytes(b"x")
    out = tmp_path / "voice_trimmed.mp3"
    return src, out


class TestTrimInternalSilence:
    def test_keeps_trimmed_when_reasonable(self, tmp_path):
        src, out = _paths(tmp_path)
        # 30s -> 24s: a sensible trim, well above the 50% floor.
        with patch.object(pipeline, "run") as run, \
             patch.object(pipeline, "probe_duration", side_effect=[30.0, 24.0]):
            def _touch(*a, **k):
                out.write_bytes(b"y")
            run.side_effect = _touch
            res = pipeline.trim_internal_silence(src, out)
        assert res == out

    def test_reverts_when_over_trimmed(self, tmp_path):
        src, out = _paths(tmp_path)
        # 30s -> 10s is < 50% of input: threshold too aggressive, keep original.
        with patch.object(pipeline, "run"), \
             patch.object(pipeline, "probe_duration", side_effect=[30.0, 10.0]):
            res = pipeline.trim_internal_silence(src, out)
        assert res == src

    def test_reverts_when_output_empty(self, tmp_path):
        src, out = _paths(tmp_path)
        with patch.object(pipeline, "run"), \
             patch.object(pipeline, "probe_duration", side_effect=[30.0, 0.0]):
            res = pipeline.trim_internal_silence(src, out)
        assert res == src

    def test_reverts_when_ffmpeg_fails(self, tmp_path):
        src, out = _paths(tmp_path)
        with patch.object(pipeline, "run", side_effect=RuntimeError("ffmpeg boom")), \
             patch.object(pipeline, "probe_duration", return_value=30.0):
            res = pipeline.trim_internal_silence(src, out)
        assert res == src

    def test_builds_silenceremove_filter_with_params(self, tmp_path):
        src, out = _paths(tmp_path)
        seen = {}

        def _capture(args, *a, **k):
            seen["args"] = args
            out.write_bytes(b"y")

        with patch.object(pipeline, "run", side_effect=_capture), \
             patch.object(pipeline, "probe_duration", side_effect=[30.0, 25.0]):
            pipeline.trim_internal_silence(
                src, out, threshold_db=-38.0, min_silence=0.5, keep_silence=0.15)
        af = seen["args"][seen["args"].index("-af") + 1]
        assert "silenceremove=stop_periods=-1" in af
        assert "stop_duration=0.5" in af
        assert "stop_threshold=-38.0dB" in af
        assert "stop_silence=0.15" in af
