"""Shared pytest plumbing for the bezyzuta test suite.

pipeline.py imports `requests` at module load (used for Gemini /
Cloudflare HTTP). Heavy ML deps (chatterbox, piper, mediapipe, torch,
faster-whisper, ultralytics) are all lazy-imported INSIDE the functions
that need them, so `import pipeline` itself only needs the stdlib +
requests. Tests cover the pure-Python helpers and don't go anywhere
near the ML imports.
"""

import sys
from pathlib import Path

import pytest

# Project root on sys.path so `import pipeline` works when running
# `pytest` from anywhere in the repo.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_module_globals():
    """Reset mutable module-level state between tests so test order can't leak
    one test's encoder choice / disabled photo source into the next."""
    import pipeline
    pipeline._VIDEO_ENCODER_MODE = "auto"
    pipeline._NVENC_CACHED = None
    # Pretend yt-dlp lacks --remote-components so download tests don't spend a
    # subprocess call probing --help (keeps their mock call sequence clean).
    pipeline._YTDLP_EJS_PROBED = False
    try:
        pipeline._DISABLED_PHOTO_SOURCES.clear()
    except Exception:
        pass
    yield
