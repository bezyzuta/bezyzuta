#!/usr/bin/env python3
"""Launcher for the packaged Windows .exe.

This is a *bootstrapper*, not the app itself. A PyInstaller exe ships its
own Python and can't use the project's .venv — and bundling torch /
chatterbox / whisper would make a multi-GB binary that breaks CUDA. So this
tiny exe (stdlib only) just finds the project's .venv + gui.py and launches
them as a subprocess, exactly like double-clicking start-gui.bat. The real
GUI then runs in the .venv with all dependencies available.

Errors are always shown and the window is kept open (pause) so a failure is
readable instead of a console that flashes and vanishes.
"""
import os
import subprocess
import sys
from pathlib import Path


def _pause(msg: str = "\nEnter drücken zum Schließen...") -> None:
    try:
        input(msg)
    except Exception:
        pass


def _find_project(start: Path) -> Path | None:
    """Locate the project folder (the one containing gui.py + pipeline.py).
    Searches the current working dir and walks up from the exe location."""
    candidates = [Path.cwd(), start]
    p = start
    for _ in range(6):
        p = p.parent
        candidates.append(p)
    seen = set()
    for c in candidates:
        try:
            c = c.resolve()
        except Exception:
            continue
        if c in seen:
            continue
        seen.add(c)
        if (c / "gui.py").is_file() and (c / "pipeline.py").is_file():
            return c
    return None


def main() -> int:
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
    else:
        here = Path(__file__).resolve().parent

    project = _find_project(here)
    if project is None:
        print("=" * 56)
        print(" Bezys Shorts Generator — Start fehlgeschlagen")
        print("=" * 56)
        print("\nProjektordner (mit gui.py + pipeline.py) nicht gefunden.")
        print("Lege die .exe IN den Projektordner (oder lass den")
        print("dist-Ordner darin) und starte erneut.")
        print(f"\nGesucht ab: {here}")
        _pause()
        return 1

    # Use the project's virtualenv Python (has torch/chatterbox/whisper/etc).
    venv_py = project / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        py = str(venv_py)
    else:
        py = sys.executable if not getattr(sys, "frozen", False) else "python"
        print(f"WARNUNG: .venv nicht gefunden unter {venv_py}")
        print(f"         Versuche System-Python: {py}")

    print(f"Starte Bezys Shorts Generator aus:\n  {project}\n")
    try:
        rc = subprocess.run([py, str(project / "gui.py")], cwd=str(project)).returncode
    except FileNotFoundError:
        print(f"\nFEHLER: Python nicht gefunden ({py}).")
        print("Ist die .venv eingerichtet? (python -m venv .venv)")
        _pause()
        return 1
    except Exception as e:
        print(f"\nFEHLER beim Start: {e}")
        _pause()
        return 1

    # The GUI ran in the .venv. If it errored, keep the window so the
    # traceback above is readable.
    if rc != 0:
        print(f"\nGUI mit Code {rc} beendet (Fehler oben).")
        _pause()
    return rc


if __name__ == "__main__":
    sys.exit(main())
