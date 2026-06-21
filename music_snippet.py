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

# Pro Clip ein anderer Bild-„Winkel", damit nicht jedes Snippet dasselbe Bild
# bekommt (Grok liefert bei identischem Prompt sonst dasselbe Bild).
_IMAGE_VARIATIONS = [
    "wide establishing shot", "intimate close-up", "low angle shot",
    "high angle overhead shot", "side profile view", "shot from behind",
    "dramatic over-the-shoulder framing", "symmetrical centered composition",
    "rule-of-thirds composition", "dutch angle, tilted frame",
    "extreme close-up detail", "full body wide framing",
]


def _vary_theme(theme: str, i: int) -> str:
    """Das Bild-Thema pro Clip leicht abwandeln (andere Perspektive + Marker),
    damit jeder Clip ein anderes Bild erhält — auch bei Grok (kein Seed)."""
    import random as _r
    angle = _IMAGE_VARIATIONS[(i - 1) % len(_IMAGE_VARIATIONS)]
    # zusätzlicher Zufalls-Marker erzwingt bei Grok eine neue Generierung
    return f"{theme.strip()}, {angle}, variation {i} seed {_r.randint(1, 999999)}"


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


def _make_pingpong(clip: Path, out_path: Path) -> Path:
    """Aus dem kurzen LTX-Clip eine nahtlose Ping-Pong-Version bauen (vorwärts
    + rückwärts aneinandergehängt). Beim späteren Loopen springt es so nicht
    hart auf den Anfang zurück, sondern läuft durchgehend hin und her — kein
    sichtbarer Loop-Sprung. `reverse` puffert den ganzen Clip; bei ~4-8s ok."""
    P.run_capture_stderr([
        "ffmpeg", "-y", "-i", str(clip),
        "-filter_complex", "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
        "-map", "[v]", "-an",
        *P._vcodec("fast"),
        "-pix_fmt", "yuv420p",
        str(out_path),
    ])
    return out_path


def _render_snippet_from_clip(clip: Path, song: Path, song_start: float, dur: float,
                              ass_path: Path, out_path: Path, cfg,
                              saturation: float = 0.15) -> None:
    """Wie _render_snippet, aber Quelle ist ein ANIMIERTER Clip (LTX-Video)
    statt eines Standbilds. Der Clip wird zu einem nahtlosen Ping-Pong gemacht,
    formatfüllend skaliert, geloopt bis er die Snippet-Länge erreicht, dann
    S/W + dunkel + Korn + zentrierte Lyrics, darunter der Song-Ausschnitt."""
    w, h = int(cfg.target_w), int(cfg.target_h)
    # Nahtlose Ping-Pong-Quelle bauen; klappt das nicht, den Roh-Clip nehmen.
    src = clip
    try:
        src = _make_pingpong(clip, clip.with_name(clip.stem + "_pp.mp4"))
    except Exception:
        src = clip
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"hue=s={max(0.0, float(saturation)):.2f},"   # fast S/W, nur ein Hauch Farbe
        f"eq=contrast=1.08:brightness=-0.06:gamma=0.95,"
        f"noise=alls=9:allf=t,"
        f"subtitles={ass_path.name},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        # Ping-Pong-Clip nahtlos loopen, bis die Snippet-Länge erreicht ist.
        "-stream_loop", "-1", "-t", f"{dur:.2f}", "-i", str(src),
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


# Ken-Burns-Varianten (zoom_in, dx, dy): pro Clip eine andere → die vielen
# Snippets bewegen sich unterschiedlich statt alle gleich. dx/dy = Schwenk-
# richtung (-1/0/1).
_KB_VARIANTS = [
    (True,  1,  0), (True, -1,  0), (True,  0,  1), (True,  1,  1),
    (True, -1,  1), (False, 1,  0), (False, -1, -1), (False, 0, -1),
    (False, 1, -1), (True, -1, -1),
]


def _ken_burns_zoompan(frames: int, fps: int, w: int, h: int, variant) -> str:
    """zoompan-Filter für eine Ken-Burns-Variante (rein/raus + Schwenkrichtung).
    on-basierte lineare Kurve = vorhersehbar (kein zappeln)."""
    zoom_in, dx, dy = variant
    f = max(1, frames)
    # 1.0↔1.30 linear über den Clip.
    zexpr = f"1.0+0.30*on/{f}" if zoom_in else f"1.30-0.30*on/{f}"
    xexpr = f"iw/2-(iw/zoom/2)+(iw*0.09)*{dx}*(on/{f}-0.5)"
    yexpr = f"ih/2-(ih/zoom/2)+(ih*0.06)*{dy}*(on/{f}-0.5)"
    return (f"zoompan=z='{zexpr}':d={f}:x='{xexpr}':y='{yexpr}'"
            f":s={w}x{h}:fps={fps}")


def _render_snippet(image: Path, song: Path, song_start: float, dur: float,
                    ass_path: Path, out_path: Path, cfg, on_step=None,
                    kb_variant=None, saturation: float = 0.15) -> None:
    """Einen 9:16-Clip rendern: Standbild → Ken-Burns (variabel pro Clip),
    fast S/W + dunkel + Filmkorn, zentrierte Lyrics, darunter der Song-Ausschnitt."""
    w, h = int(cfg.target_w), int(cfg.target_h)
    fps = 30
    frames = max(1, int(round(dur * fps)))
    # 2x vorskalieren glättet zoompan (sonst ruckelt es auf kleinen Bildern).
    big_w, big_h = w * 2, h * 2
    variant = kb_variant or _KB_VARIANTS[0]
    vf = (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
        f"crop={big_w}:{big_h},"
        f"{_ken_burns_zoompan(frames, fps, w, h, variant)},"
        f"hue=s={max(0.0, float(saturation)):.2f},"   # fast S/W, nur ein Hauch Farbe
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
    # Ein Snippet darf NIE länger sein als der Song selbst (sonst läuft am Ende
    # Stille / das Bild ohne Ton weiter). Bei kürzerem Song: Clip = Songlänge.
    if song_dur < dur:
        step(f"      Song nur {song_dur:.1f}s — Snippet-Länge von {dur:.0f}s auf {song_dur:.1f}s gekürzt")
        dur = song_dur
    step(f"      Song: {song.name} ({song_dur:.0f}s) → {n} Snippets à {dur:.1f}s")

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
        # Bild — Thema PRO CLIP variieren, sonst kommt überall dasselbe Bild.
        img = work / f"img_{i:02d}.png"
        clip_theme = _vary_theme(theme, i)
        if not _generate_dark_image(clip_theme, img, cfg, on_step=step):
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
                step(f"      LTX-Video übersprungen — nutze Ken-Burns-Standbild:")
                step(f"      {str(e)[:600]}")
                anim_clip = None
        # Render
        out_mp4 = out_root / f"{base_slug}_snippet_{i:02d}.mp4"
        # Sättigung: 0 = komplett S/W, ~0.15 = nur ein Hauch Farbe (Default),
        # per job["snippet_saturation"] einstellbar.
        sat = float(job.get("snippet_saturation", 0.15))
        try:
            if anim_clip is not None:
                _render_snippet_from_clip(anim_clip, song, s_start, dur, ass, out_mp4, cfg,
                                          saturation=sat)
            else:
                # Pro Clip eine zufällige Ken-Burns-Variante → jeder Clip
                # bewegt sich anders (rein/raus, andere Schwenkrichtung).
                kb = random.choice(_KB_VARIANTS)
                _render_snippet(img, song, s_start, dur, ass, out_mp4, cfg,
                                on_step=step, kb_variant=kb, saturation=sat)
            outputs.append(out_mp4)
            step(f"      ✓ {out_mp4.name}")
        except Exception as e:
            step(f"  ── Clip {i} FAILED: {str(e)[:200]}")
            continue

    step(f"[SNIPPET DONE] {len(outputs)}/{n} Clips erstellt → {out_root}")
    return outputs
