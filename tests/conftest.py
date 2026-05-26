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

# Project root on sys.path so `import pipeline` works when running
# `pytest` from anywhere in the repo.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
