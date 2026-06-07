# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Bezys Shorts Generator launcher.

Build (on Windows, repo root):  build_exe.bat
or:  .venv\\Scripts\\python.exe -m PyInstaller --noconfirm bezys.spec

The exe is a TINY stdlib-only bootstrapper (app_launcher.py). It does NOT
bundle Gradio or the ML stack — it just finds the project's .venv and runs
gui.py in it, so the real app has all its dependencies. One-file output:
dist/BezysShortsGenerator.exe — drop it in the project folder and double-click.
"""

block_cipher = None

a = Analysis(
    ["app_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Nothing heavy is imported by the launcher; keep it tiny.
    excludes=["gradio", "torch", "torchaudio", "chatterbox", "faster_whisper",
              "ultralytics", "mediapipe", "cv2", "numpy", "PIL", "requests"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BezysShortsGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,          # show the pipeline log + keep errors readable
    icon=None,
)
