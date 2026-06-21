#!/usr/bin/env python3
"""Lokales KI-Bild-zu-Video über LTX-Video (Lightricks) — gratis, auf deiner
eigenen GPU, kein Abo.

Animiert ein Standbild zu echtem Bewegtbild (Kamera-Push, Wind, Licht …).
LTX-Video ist das schnellste offene Image-to-Video-Modell für Consumer-GPUs
und passt mit CPU-Offload auf eine RTX 3080 (10 GB).

WICHTIG — eigener venv:
  Die Diffusion-Stacks (torch/diffusers/numpy) kollidieren mit dem Chatterbox-
  Stack im Haupt-venv. Darum läuft LTX-Video in einem SEPARATEN venv und wird
  per Subprozess aufgerufen — `cfg.ltxv_python` zeigt auf dessen python.exe.
  Setup siehe LTXV.md.

Best-effort: jede Fehlerquelle (kein venv / OOM / Modell fehlt) wirft, der
Aufrufer fällt dann auf das Ken-Burns-Standbild zurück. Ein Render bricht NIE
an der Animation ab.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


# Läuft IM ltxv-venv (nicht im Haupt-venv). Nimmt: bild, prompt, out, frames,
# width, height, steps, fps. Schreibt einen mp4 und gibt "OK" aus.
_LTXV_CHILD = r'''
import sys
img, prompt, out, frames, width, height, steps, fps = sys.argv[1:9]
frames, width, height, steps, fps = int(frames), int(width), int(height), int(steps), int(fps)
import torch
from diffusers import LTXImageToVideoPipeline
from diffusers.utils import export_to_video, load_image

dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
pipe = LTXImageToVideoPipeline.from_pretrained(sys.argv[9], torch_dtype=dtype)
# CPU-Offload haelt den VRAM-Bedarf klein genug fuer 10 GB.
try:
    pipe.enable_model_cpu_offload()
except Exception:
    pipe.to("cuda" if torch.cuda.is_available() else "cpu")

image = load_image(img).convert("RGB").resize((width, height))
result = pipe(
    image=image,
    prompt=prompt,
    negative_prompt="static, still image, frozen, motionless, no motion, worst quality, blurry, distorted, watermark, text",
    width=width, height=height, num_frames=frames,
    num_inference_steps=steps,
)
export_to_video(result.frames[0], out, fps=fps)
print("OK", flush=True)
'''


def _motion_prompt(theme: str) -> str:
    """Bewegungs-Prompt aus dem Bild-Thema bauen. Bewusst BEWEGUNGS-betont
    (nicht 'subtle/slow' — das ergab fast statische Clips), damit LTX-Video
    sichtbar animiert: Bewegung im Motiv + Kamerafahrt."""
    base = (theme or "cinematic scene").strip()
    return (f"{base}, the scene is in motion, people and elements moving "
            "naturally, smooth dynamic cinematic camera movement, flowing "
            "motion, drifting light and shadow, moody dark cinematic aesthetic")


def animate_image(image_path: Path, out_clip: Path, theme: str, cfg,
                  on_step=None) -> Path:
    """Ein Standbild zu einem kurzen Video animieren (LTX-Video, eigener venv).
    Gibt den Clip-Pfad zurueck oder wirft — der Aufrufer faengt das ab und
    nimmt dann das Standbild."""
    def log(m):
        if on_step:
            try: on_step(m)
            except Exception: pass

    py = (getattr(cfg, "ltxv_python", "") or "").strip()
    if not py:
        raise RuntimeError(
            "ltxv_python ist nicht gesetzt — eigener LTX-Video-venv noetig "
            "(siehe LTXV.md). Animation uebersprungen.")
    if not Path(py).expanduser().is_file():
        raise RuntimeError(f"ltxv_python zeigt auf kein Interpreter: {py}")

    # LTX-Video verlangt: Hoehe/Breite durch 32 teilbar, Frames = 8k+1.
    w = max(32, (int(getattr(cfg, "ltxv_width", 480)) // 32) * 32)
    h = max(32, (int(getattr(cfg, "ltxv_height", 832)) // 32) * 32)
    frames = int(getattr(cfg, "ltxv_frames", 97))
    if (frames - 1) % 8 != 0:
        frames = ((frames - 1) // 8) * 8 + 1     # auf 8k+1 runden
    steps = int(getattr(cfg, "ltxv_steps", 30))
    fps = int(getattr(cfg, "ltxv_fps", 24))
    model = (getattr(cfg, "ltxv_model", "") or "Lightricks/LTX-Video").strip()
    prompt = _motion_prompt(theme)

    log(f"      LTX-Video: animiere Bild ({w}x{h}, {frames}f, {steps} steps) — kann 1-3 Min dauern")
    cmd = [py, "-c", _LTXV_CHILD, str(image_path), prompt, str(out_clip),
           str(frames), str(w), str(h), str(steps), str(fps), model]
    # Vollständige Ausgabe (inkl. tqdm + Traceback) in eine Log-Datei schreiben,
    # damit wir bei einem Fehlschlag NACH 5 Min wissen WARUM (statt zu raten).
    log_file = out_clip.parent / "ltxv_log.txt"
    try:
        with open(log_file, "w", encoding="utf-8", errors="ignore") as lf:
            proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=1800)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("LTX-Video Timeout (>30 Min)") from e
    if proc.returncode != 0 or not out_clip.is_file() or out_clip.stat().st_size < 1024:
        tail = ""
        try:
            tail = "\n".join(log_file.read_text(encoding="utf-8", errors="ignore")
                             .strip().splitlines()[-8:])
        except Exception:
            pass
        raise RuntimeError(
            f"LTX-Video fehlgeschlagen (exit {proc.returncode}). Letzte Zeilen "
            f"(volles Log: {log_file}):\n{tail[:500]}")
    log(f"      LTX-Video: Clip fertig → {out_clip.name}")
    return out_clip
