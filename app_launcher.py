#!/usr/bin/env python3
"""Entry point for the packaged Windows .exe (see bezys.spec / build_exe.bat).

This is intentionally tiny: it just boots the existing Gradio GUI. The exe is
a thin launcher — pipeline.py and the heavy ML deps load from the project's
.venv at runtime, exactly like `python gui.py`. Run the exe from inside the
project folder (next to gui.py, pipeline.py, config.json).
"""
import os
import sys
from pathlib import Path

# When frozen by PyInstaller, make the project dir (where the exe lives) the
# working dir so config.json / relative paths resolve like a normal run.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)

from gui import main

if __name__ == "__main__":
    main()
