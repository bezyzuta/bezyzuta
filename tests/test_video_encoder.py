"""NVENC-first video encoder selection with auto/nvenc/cpu modes."""

from unittest.mock import patch

import pipeline


def _reset():
    pipeline._NVENC_CACHED = None
    pipeline.set_video_encoder_mode("auto")


def test_cpu_mode_forces_libx264():
    _reset()
    pipeline.set_video_encoder_mode("cpu")
    assert pipeline._vcodec("standard")[:2] == ["-c:v", "libx264"]
    assert pipeline._vcodec("fast")[:2] == ["-c:v", "libx264"]


def test_nvenc_mode_forces_nvenc():
    _reset()
    pipeline.set_video_encoder_mode("nvenc")
    assert pipeline._vcodec("standard")[:2] == ["-c:v", "h264_nvenc"]
    assert "-cq" in pipeline._vcodec("standard")


def test_auto_probes_ffmpeg_and_caches():
    _reset()
    pipeline.set_video_encoder_mode("auto")

    class _P:
        stdout = "... h264_nvenc ... libx264 ..."
    with patch("subprocess.run", return_value=_P()) as run:
        assert pipeline._vcodec("standard")[:2] == ["-c:v", "h264_nvenc"]
        # Second call must use the cache, not probe again.
        pipeline._vcodec("fast")
    assert run.call_count == 1


def test_auto_falls_back_to_cpu_when_no_nvenc():
    _reset()
    pipeline.set_video_encoder_mode("auto")

    class _P:
        stdout = "... libx264 ... libvpx ..."  # no nvenc listed
    with patch("subprocess.run", return_value=_P()):
        assert pipeline._vcodec("standard")[:2] == ["-c:v", "libx264"]


def test_auto_falls_back_when_ffmpeg_missing():
    _reset()
    pipeline.set_video_encoder_mode("auto")
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert pipeline._vcodec("standard")[:2] == ["-c:v", "libx264"]
    _reset()


def test_invalid_mode_defaults_to_auto():
    pipeline.set_video_encoder_mode("garbage")
    assert pipeline._VIDEO_ENCODER_MODE == "auto"
    _reset()
