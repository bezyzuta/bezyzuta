#!/usr/bin/env python3
"""Musik-Snippet-Generator: viele optisch verschiedene 9:16-Clips mit DEMSELBEN
Song, um einen Track auf TikTok/Reels/Shorts zu pushen.

Pro Clip:
  • ein frisch per KI generiertes Bild (dunkle S/W-Ästhetik)
  • Ken-Burns-Zoom (langsames Reinzoomen) für Bewegung
  • Schwarzweiss + abgedunkelt + Filmkorn-Look
  • der Song-Ausschnitt als Ton
  • die Songtext-Zeilen (per Whisper aus dem Song transkribiert) klein und
    mittig eingeblendet, synchron zum Ton

Eigenständiger Pfad — hängt sich NICHT in run_one. Nutzt aber die bewährten
Pipeline-Bausteine (Whisper, KI-Bild-Fetcher, write_ass, _vcodec) wieder.
Gerendert wird über ffmpeg; Fehler pro Clip werden abgefangen, der Lauf macht
mit dem nächsten weiter statt abzubrechen.
"""

from __future__ import annotations

import random
from pathlib import Path

import pipeline as P


# ── Bildstil: dunkle, körnige S/W-Ästhetik ──────────────────────────────────
_DARK_BW_SUFFIX = (
    ", dark moody cinematic atmosphere, deep shadows, high contrast, "
    "desaturated, grainy film aesthetic, low key lighting, melancholic, "
    "no text, no watermark"
)


def _resolve_song(job: dict, cfg) -> Path:
    """Den zu pushenden Song bestimmen: explizit job['song_path'], sonst der in
    der GUI gewählte Track aus dem Musik-Ordner, sonst ein zufälliger daraus."""
    explicit = (job.get("song_path") or "").strip()
    if explicit and Path(explicit).expanduser().is_file():
        return Path(explicit).expanduser()
    music_dir = (job.get("music_dir") or "").strip()
    track = (job.get("music_track") or "").strip()
    picked = P.pick_music_track(music_dir, track)
    if picked is None:
        raise RuntimeError(
            "Kein Song gefunden. Musik-Ordner setzen (und optional einen Track "
            "wählen) oder job['song_path'] auf eine Audiodatei zeigen lassen.")
    return picked


def _lyrics_window(words: list, start: float, dur: float) -> list:
    """Die Whisper-Wörter [(s,e,wort), …] auf das Fenster [start, start+dur]
    filtern und die Zeiten auf 0 (= Clip-Anfang) zurückrechnen. Wörter, die
    ins Fenster ragen, werden am Rand abgeschnitten."""
    end = start + dur
    out = []
    for (ws, we, w) in words:
        if we <= start or ws >= end:
            continue
        ns = max(0.0, ws - start)
        ne = min(dur, we - start)
        if ne - ns < 0.02:
            continue
        out.append((ns, ne, w))
    return out


def _generate_dark_image(prompt: str, out_path: Path, cfg, on_step=None) -> bool:
    """Ein 9:16-Bild im dunklen S/W-Stil erzeugen. Provider-Kaskade wie in
    run_one: Grok (wenn an) → Cloudflare Flux → Pollinations. True bei Erfolg.
    Schwarze/leere Frames werden von den Save-Helfern abgelehnt → nächster
    Provider. Best-effort: False statt Exception, damit der Clip übersprungen
    werden kann."""
    def log(m):
        if on_step:
            try: on_step(m)
            except Exception: pass

    full = prompt.strip() + _DARK_BW_SUFFIX
    # Grok CLI (vertikal), wenn aktiviert.
    if bool(getattr(cfg, "use_grok_cli", False)):
        try:
            P.fetch_image_from_grok_cli(full, out_path, cfg, aspect="9:16", on_step=on_step)
            return True
        except Exception as e:
            log(f"      grok fehlgeschlagen ({str(e)[:100]}) → Cloudflare/Pollinations")
    # Cloudflare Flux (720×1280 → auf 9:16 zuschneiden).
    if getattr(cfg, "cloudflare_account_id", "") and getattr(cfg, "cloudflare_api_token", ""):
        try:
            P.fetch_image_from_cloudflare(full, out_path, cfg, width=720, height=1280,
                                          seed=random.randint(1, 1_000_000))
            P._faceless_recrop(out_path, ar=9 / 16)
            return True
        except Exception as e:
            log(f"      Cloudflare fehlgeschlagen ({str(e)[:100]}) → Pollinations")
    # Pollinations (kein Key).
    try:
        P.fetch_image_from_pollinations(full, out_path, width=720, height=1280,
                                        seed=random.randint(1, 1_000_000))
        P._faceless_recrop(out_path, ar=9 / 16)
        return True
    except Exception as e:
        log(f"      Pollinations fehlgeschlagen ({str(e)[:100]})")
    return False


def _render_snippet_from_clip(clip: Path, song: Path, song_start: float, dur: float,
                              ass_path: Path, out_path: Path, cfg) -> None:
    """Wie _render_snippet, aber Quelle ist ein ANIMIERTER Clip (LTX-Video)
    statt eines Standbilds. Der Clip wird formatfüllend skaliert, geloopt bis
    er die Snippet-Länge erreicht, dann S/W + dunkel + Korn + zentrierte
    Lyrics, darunter der Song-Ausschnitt."""
    w, h = int(cfg.target_w), int(cfg.target_h)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"hue=s=0,"
        f"eq=contrast=1.08:brightness=-0.06:gamma=0.95,"
        f"noise=alls=9:allf=t,"
        f"subtitles={ass_path.name},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        # Clip loopen, bis die Snippet-Länge erreicht ist (LTX macht nur ~4s).
        "-stream_loop", "-1", "-t", f"{dur:.2f}", "-i", str(clip),
        "-ss", f"{song_start:.2f}", "-t", f"{dur:.2f}", "-i", str(song),
        "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]", "-map", "1:a",
        *P._vcodec("standard"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{dur:.2f}", "-movflags", "+faststart",
        str(out_path),
    ]
    P.run_capture_stderr(cmd, cwd=str(ass_path.parent))


def _render_snippet(image: Path, song: Path, song_start: float, dur: float,
                    ass_path: Path, out_path: Path, cfg, on_step=None) -> None:
    """Einen 9:16-Clip rendern: Standbild → Ken-Burns-Zoom, S/W + dunkel +
    Filmkorn, zentrierte Lyrics, darunter der Song-Ausschnitt. ffmpeg-Filter
    nach bewährtem Muster; subtitles liest die ASS aus dem cwd (wie in
    compose_short)."""
    w, h = int(cfg.target_w), int(cfg.target_h)
    fps = 30
    frames = max(1, int(round(dur * fps)))
    # 2x vorskalieren glättet zoompan (sonst ruckelt es auf kleinen Bildern),
    # dann langsam von 1.0 auf 1.12 zoomen, mittig.
    big_w, big_h = w * 2, h * 2
    vf = (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
        f"crop={big_w}:{big_h},"
        f"zoompan=z='min(zoom+0.0009,1.12)':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
        f"hue=s=0,"                                   # Schwarzweiss
        f"eq=contrast=1.08:brightness=-0.06:gamma=0.95,"  # abgedunkelt
        f"noise=alls=9:allf=t,"                       # Filmkorn
        f"subtitles={ass_path.name},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{dur:.2f}", "-i", str(image),
        "-ss", f"{song_start:.2f}", "-t", f"{dur:.2f}", "-i", str(song),
        "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]", "-map", "1:a",
        *P._vcodec("standard"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{dur:.2f}", "-movflags", "+faststart",
        str(out_path),
    ]
    P.run_capture_stderr(cmd, cwd=str(ass_path.parent))


def run_music_snippet(job: dict, cfg, on_step=None) -> list:
    """N optisch verschiedene Musik-Snippets aus einem Song bauen. Gibt die
    Liste der erzeugten mp4-Pfade zurück."""
    def step(msg: str):
        # Immer ins Terminal UND (wenn vorhanden) in die GUI — sonst sieht man
        # im Terminal nichts, weil die GUI on_step abfängt.
        if on_step:
            try: on_step(msg)
            except Exception: pass
        print(msg)

    base_slug = job.get("slug") or "snippet"
    n = max(1, min(int(job.get("snippet_count", job.get("batch_count", 5))), 50))
    dur = float(job.get("snippet_duration", job.get("target_duration", 15.0)))
    dur = max(5.0, min(dur, 60.0))
    theme = (job.get("topic") or job.get("snippet_theme") or "cinematic moody scene").strip()

    out_root = Path(cfg.output_dir).expanduser()
    work = out_root / f"{base_slug}__snippets"
    work.mkdir(parents=True, exist_ok=True)

    step(f"[SNIPPET 1/3] Song bestimmen")
    song = _resolve_song(job, cfg)
    song_dur = P._media_duration(song)
    if song_dur <= 1.0:
        raise RuntimeError(f"Song-Dauer nicht lesbar: {song}")
    step(f"      Song: {song.name} ({song_dur:.0f}s) → {n} Snippets à {dur:.0f}s")

    # Lyrics EINMAL transkribieren (teuer), dann pro Clip ein Fenster nehmen.
    words: list = []
    if bool(job.get("snippet_lyrics", True)):
        step(f"[SNIPPET 2/3] Songtext mit Whisper transkribieren")
        try:
            # Songs können in JEDER Sprache sein (z.B. brasilianisches
            # Portugiesisch) — daher Lyrics IMMER automatisch erkennen, nicht
            # die Stimmen-Sprache (tts_language) nehmen. Per job-Feld
            # "snippet_lyrics_lang" überschreibbar (z.B. "pt" erzwingen).
            lyrics_lang = str(job.get("snippet_lyrics_lang", "auto") or "auto")
            words, _dev = P.transcribe_words_best(
                song, cfg.whisper_model,
                device=str(job.get("whisper_device", "auto")),
                use_whisperx=bool(getattr(cfg, "use_whisperx", False)),
                language=lyrics_lang,
                whisperx_python=str(getattr(cfg, "whisperx_python", "") or ""),
                on_step=step,
            )
            step(f"      {len(words)} Wörter transkribiert (Sprache: {lyrics_lang})")
        except Exception as e:
            step(f"      WARN: Transkription fehlgeschlagen ({str(e)[:140]}) — Snippets ohne Text")
            words = []

    step(f"[SNIPPET 3/3] {n} Clips rendern")
    max_start = max(0.0, song_dur - dur)
    outputs: list = []
    font = str(job.get("caption_font", "Impact"))
    small_size = int(job.get("snippet_font_size", max(40, int(cfg.target_h * 0.030))))
    for i in range(1, n + 1):
        step(f"  ── Clip {i}/{n}")
        # Bild
        img = work / f"img_{i:02d}.png"
        if not _generate_dark_image(theme, img, cfg, on_step=step):
            step(f"  ── Clip {i}: kein Bild erzeugt — übersprungen")
            continue
        # Song-Fenster (zufällig, für Abwechslung)
        s_start = random.uniform(0.0, max_start) if max_start > 0.5 else 0.0
        # Lyrics-Fenster + ASS (zentriert, klein)
        win = _lyrics_window(words, s_start, dur) if words else []
        ass = work / f"lyrics_{i:02d}.ass"
        try:
            P.write_ass(
                win, int(cfg.target_w), int(cfg.target_h), ass,
                font_name=font, font_size=small_size,
                primary_color=str(job.get("caption_color", "#FFFFFF")),
                outline_color=str(job.get("caption_stroke_color", "#000000")),
                outline_width=int(job.get("caption_stroke_width", 3)),
                caption_position="center",
                enable_captions=bool(win),
                total_duration=dur,
            )
        except Exception as e:
            step(f"      WARN: Untertitel fehlgeschlagen ({str(e)[:100]}) — Clip ohne Text")
            # Leere ASS, damit der subtitles-Filter nicht crasht.
            ass.write_text("[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n\n[Events]\n",
                           encoding="utf-8")
        # Optional: das Standbild per LTX-Video zu echtem Bewegtbild animieren
        # (eigener venv, GPU). Fällt bei JEDEM Fehler auf Ken-Burns zurück.
        anim_clip = None
        if bool(getattr(cfg, "use_ltx_video", False)):
            try:
                import ltx_video
                anim_clip = ltx_video.animate_image(
                    img, work / f"anim_{i:02d}.mp4", theme, cfg, on_step=step)
            except Exception as e:
                step(f"      LTX-Video übersprungen ({str(e)[:140]}) — nutze Ken-Burns-Standbild")
                anim_clip = None
        # Render
        out_mp4 = out_root / f"{base_slug}_snippet_{i:02d}.mp4"
        try:
            if anim_clip is not None:
                _render_snippet_from_clip(anim_clip, song, s_start, dur, ass, out_mp4, cfg)
            else:
                _render_snippet(img, song, s_start, dur, ass, out_mp4, cfg, on_step=step)
            outputs.append(out_mp4)
            step(f"      ✓ {out_mp4.name}")
        except Exception as e:
            step(f"  ── Clip {i} FAILED: {str(e)[:200]}")
            continue

    step(f"[SNIPPET DONE] {len(outputs)}/{n} Clips erstellt → {out_root}")
    return outputs
