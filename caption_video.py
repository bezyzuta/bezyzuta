#!/usr/bin/env python3
"""Eigenes Video + Untertitel: Du lädst dein fertiges Video hoch (z.B. aus
Canva), das Tool transkribiert die Tonspur mit WhisperX und brennt die Texte
mittig ins Video. Sonst wird NICHTS verändert — keine Bilder, kein Schnitt,
keine Musik, Auflösung/Ton bleiben wie sie sind.

Eigener, schlanker Pfad (run_caption_video). Nutzt die bewährten Pipeline-
Bausteine (transcribe_words_best mit WhisperX, write_ass mit zentrierter
Position, _vcodec). Best-effort: schlägt die Transkription fehl, kommt das
Video trotzdem (nur ohne Text) raus — der Lauf bricht nie ab.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pipeline as P


def _probe_dimensions(video: Path) -> tuple[int, int]:
    """Breite/Höhe des Videos via ffprobe (für korrekte Untertitel-Position).
    Fällt auf 1080x1920 zurück, wenn nicht lesbar."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
            capture_output=True, text=True, check=True,
        )
        w, h = r.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def run_caption_video(job: dict, cfg, on_step=None) -> Path:
    """Ein vom User hochgeladenes Video nehmen, die Tonspur mit WhisperX
    transkribieren und die Texte MITTIG ins Video brennen. Gibt den Pfad des
    fertigen Videos zurück."""
    def step(msg: str):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        print(msg)

    src = (job.get("caption_video_path") or "").strip()
    if not src:
        raise RuntimeError(
            "Kein Video hochgeladen. Im Bild-Overlay-Bereich dein fertiges "
            "Video hochladen (oder job['caption_video_path'] setzen).")
    video = Path(src).expanduser()
    if not video.is_file():
        raise RuntimeError(f"Video nicht gefunden: {video}")

    base_slug = job.get("slug") or "captioned"
    out_root = Path(cfg.output_dir).expanduser()
    work = out_root / f"{base_slug}__captioned_work"
    work.mkdir(parents=True, exist_ok=True)

    w, h = _probe_dimensions(video)
    step(f"[1/3] Video: {video.name} ({w}x{h})")

    # Ton rausziehen und mit WhisperX transkribieren (Sprache automatisch).
    step("[2/3] Tonspur transkribieren (WhisperX)")
    audio = work / "audio.wav"
    words: list = []
    try:
        P.run_capture_stderr([
            "ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(audio),
        ])
        lang = str(job.get("caption_lang", "auto") or "auto")
        words, _dev = P.transcribe_words_best(
            audio, cfg.whisper_model,
            device=str(job.get("whisper_device", "auto")),
            use_whisperx=True,                       # explizit WhisperX (mit Fallback)
            language=lang,
            whisperx_python=str(getattr(cfg, "whisperx_python", "") or ""),
            on_step=step,
        )
        step(f"      {len(words)} Wörter transkribiert (Sprache: {lang})")
    except Exception as e:
        step(f"      WARN: Transkription fehlgeschlagen ({str(e)[:160]}) — Video ohne Text")
        words = []

    # Zentrierte Untertitel-ASS in der echten Video-Auflösung.
    ass = work / "captions.ass"
    P.write_ass(
        words, w, h, ass,
        font_name=str(job.get("caption_font", "Impact")),
        font_size=int(job.get("caption_font_size", 0)) or None,
        primary_color=str(job.get("caption_color", "#FFFFFF")),
        outline_color=str(job.get("caption_stroke_color", "#000000")),
        outline_width=int(job.get("caption_stroke_width", 5)),
        caption_position="center",
        pop_captions=bool(job.get("pop_captions", False)),
        enable_captions=bool(words),
        total_duration=P.probe_duration(video),
    )

    step("[3/3] Untertitel ins Video brennen")
    out = out_root / f"{base_slug}.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"subtitles={ass.name}",
        "-map", "0:v:0", "-map", "0:a?",            # Video + Ton (falls vorhanden)
        *P._vcodec("standard"),
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",                              # Originalton unverändert
        "-movflags", "+faststart",
        str(out),
    ]
    P.run_capture_stderr(cmd, cwd=str(ass.parent))
    step(f"      ✓ {out}")
    return out
