"""Audio polish: sidechain ducking + music fades + broadcast voice EQ.

ffmpeg is mocked — these assert the filter graphs and the safe fallbacks.
Run: `pytest tests/test_audio_polish.py -v`
"""

from pathlib import Path
from unittest.mock import patch

import pipeline


def _touch_last_arg(cmd, *a, **k):
    # The output path is the last element of the ffmpeg argv.
    Path(cmd[-1]).write_bytes(b"x" * 500)


class TestMixVoiceWithMusic:
    def _paths(self, tmp_path):
        v = tmp_path / "voice.mp3"; v.write_bytes(b"x" * 500)
        m = tmp_path / "music.mp3"; m.write_bytes(b"x" * 500)
        return v, m, tmp_path / "out.mp3"

    def test_sidechain_and_fades_present(self, tmp_path):
        v, m, out = self._paths(tmp_path)
        seen = {}

        def _cap(cmd, *a, **k):
            seen["fc"] = cmd[cmd.index("-filter_complex") + 1]

        with patch.object(pipeline, "_media_duration", return_value=30.0), \
             patch.object(pipeline, "run", side_effect=_cap):
            pipeline.mix_voice_with_music(v, m, 20.0, out)
        fc = seen["fc"]
        assert "sidechaincompress" in fc
        assert "afade=t=in" in fc and "afade=t=out" in fc

    def test_falls_back_to_plain_mix_when_sidechain_errors(self, tmp_path):
        v, m, out = self._paths(tmp_path)
        calls = []

        def _maybe_fail(cmd, *a, **k):
            fc = cmd[cmd.index("-filter_complex") + 1]
            calls.append(fc)
            if "sidechaincompress" in fc:
                raise RuntimeError("sidechain unsupported")

        with patch.object(pipeline, "_media_duration", return_value=30.0), \
             patch.object(pipeline, "run", side_effect=_maybe_fail):
            pipeline.mix_voice_with_music(v, m, 20.0, out)
        # Tried sidechain first, then fell back to a plain amix.
        assert len(calls) == 2
        assert "sidechaincompress" in calls[0]
        assert "sidechaincompress" not in calls[1] and "amix" in calls[1]

    def test_no_outro_fade_for_very_short_voice(self, tmp_path):
        v, m, out = self._paths(tmp_path)
        seen = {}
        with patch.object(pipeline, "_media_duration", return_value=1.0), \
             patch.object(pipeline, "run",
                          side_effect=lambda cmd, *a, **k: seen.update(
                              fc=cmd[cmd.index("-filter_complex") + 1])):
            pipeline.mix_voice_with_music(v, m, 20.0, out)
        assert "afade=t=out" not in seen["fc"]


class TestApplyVoiceEq:
    def test_builds_broadcast_chain(self, tmp_path):
        v = tmp_path / "voice.mp3"; v.write_bytes(b"x" * 500)
        out = tmp_path / "eq.mp3"
        seen = {}

        def _cap(cmd, *a, **k):
            seen["af"] = cmd[cmd.index("-af") + 1]
            _touch_last_arg(cmd)

        with patch.object(pipeline, "run", side_effect=_cap):
            res = pipeline.apply_voice_eq(v, out)
        assert res == out
        af = seen["af"]
        assert "highpass=f=80" in af
        assert "equalizer=f=3000" in af  # presence lift
        assert "acompressor" in af

    def test_falls_back_on_error(self, tmp_path):
        v = tmp_path / "voice.mp3"; v.write_bytes(b"x" * 500)
        out = tmp_path / "eq.mp3"
        with patch.object(pipeline, "run", side_effect=RuntimeError("boom")):
            res = pipeline.apply_voice_eq(v, out)
        assert res == v  # original kept
