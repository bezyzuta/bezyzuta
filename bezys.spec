# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Bezys Shorts Generator.

Build (on Windows, in the repo root):
    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm bezys.spec
or just double-click build_exe.bat.

Produces dist/BezysShortsGenerator/BezysShortsGenerator.exe — a launcher
that boots the existing Gradio GUI (gui.py) and opens the browser, so the
whole app feels like one double-click program. The heavy ML deps
(torch/chatterbox/whisper/etc.) stay in your .venv and are imported lazily
at runtime exactly as before — we deliberately do NOT bundle them into the
exe (that would make a multi-GB binary and frequently break CUDA). The exe
is a thin launcher; run it from inside the project folder (next to gui.py /
pipeline.py / config.json).
"""
import gradio, os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Gradio ships its frontend as data files + has many dynamic imports.
datas = collect_data_files("gradio") + collect_data_files("gradio_client")
hiddenimports = (
    collect_submodules("gradio")
    + collect_submodules("gradio_client")
    + ["safehttpx", "groovy"]
)

a = Analysis(
    ["app_launcher.py"],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the binary lean: the GUI launcher doesn't need these bundled —
    # they load from the .venv at runtime.
    excludes=["torch", "torchaudio", "chatterbox", "faster_whisper",
              "ultralytics", "mediapipe", "cv2", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BezysShortsGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # keep the console so you see the pipeline log
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="BezysShortsGenerator",
)
