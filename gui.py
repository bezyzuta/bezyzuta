"""Gradio GUI on top of pipeline.run_one. Run: python gui.py"""

import queue
import re
import socket
import threading
import time
import traceback
from pathlib import Path

import gradio as gr


def find_free_port(start: int = 7860, end: int = 7880) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start

from pipeline import Config, run_one


_MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}
RANDOM_PICK = "🎲 Zufällig"


def list_music_tracks(folder: str) -> list[str]:
    """Scan folder for music files, return [Zufällig, filename1, filename2, ...]."""
    if not folder:
        return [RANDOM_PICK]
    p = Path(folder.strip()).expanduser()
    if not p.is_dir():
        return [RANDOM_PICK]
    tracks = sorted(
        f.name for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in _MUSIC_EXTS
    )
    return [RANDOM_PICK] + tracks


# (display label, voice_id) — only current ElevenLabs default voices that ship with every free account.
# Legacy voices like Adam/Rachel/Domi are not guaranteed available for accounts created after their migration.
VOICES = [
    # --- Male: young / energetic (fit for Roblox shorts) ---
    ("Liam — irisch, jung (empfohlen für Roblox)", "TX3LPaxmHKxFdv7VOQHJ"),
    ("Charlie — australisch, jung",                 "IKne3meq5aSn9XLyUdCD"),
    ("Will — jung, freundlich",                     "bIHbv24MWmeRgasZH58o"),
    ("Roger — konfident, mittlere Stimme",          "CwhRBWXzGAHq8TQ4Fs17"),
    # --- Male: deep / narrator ---
    ("Brian — tief, narrativ",                      "nPczCjzI2devNBz1zQrb"),
    ("Daniel — britisch, news",                     "onwK4e9ZLuTAKqWW03F9"),
    ("George — britisch, warm",                     "JBFqnCBsd6RMkjVDRZzb"),
    ("Bill — vertrauenswürdig",                     "pqHfZKP75CvOlQylNhV4"),
    # --- Female: young / energetic ---
    ("Aria — expressiv, vielseitig",                "9BWtsMINqrJLrRacOk9x"),
    ("Sarah — jung, sanft",                         "EXAVITQu4vr4xnSDxMaL"),
    ("Laura — jung, energisch",                     "FGY2WhTYpPnrIDTdsKH5"),
    ("Jessica — jung, expressiv",                   "cgSgspJ2msm6clMCkdW9"),
    ("Matilda — freundlich, jung",                  "XrExE9yKIg1WjnnlVkGX"),
    # --- Female: deeper / mature ---
    ("Charlotte — schwedisch, mystisch",            "XB0fDUnXU5powFXDhCwa"),
    ("Alice — britisch, selbstbewusst",             "Xb7hH8MSUJpSbSDYk0k2"),
    ("Lily — britisch, warm",                       "pFZP5JQG7iQjIQuC4Bku"),
]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")
    return s or "short"


def generate(
    config_path: str,
    source_mode: str,
    source_url: str,
    channel_url: str,
    title_filter: str,
    channel_scan_limit: int,
    topic: str,
    custom_script: str,
    target_duration: float,
    clip_segments: int,
    smart_picking: bool,
    voice_id: str,
    music_dir: str,
    music_track: str,
    music_volume_pct: int,
    smart_music_start: bool,
    sfx_dir: str,
    sfx_track: str,
    sfx_volume_pct: int,
    image_count: int,
    image_duration: float,
    custom_image_prompts: str,
    uploaded_images,
    skip_images: bool,
    caption_font: str,
    caption_color: str,
    caption_stroke_color: str,
    caption_font_size: int,
    batch_count: int,
):
    log = ""
    try:
        cfg = Config.load(Path(config_path))
        cfg.elevenlabs_voice_id = voice_id
    except Exception as e:
        yield f"Config-Fehler: {e}", None
        return

    last_video = None
    n = max(1, int(batch_count))

    for run_i in range(n):
        base_slug = slugify(topic)
        if n > 1:
            base_slug = f"{base_slug}-{run_i + 1}"

        job = {
            "slug": base_slug,
            "topic": topic,
            "target_duration": float(target_duration),
            "clip_segments": int(clip_segments),
            "smart_picking": bool(smart_picking),
            "image_count": int(image_count),
            "image_duration": float(image_duration),
            "no_image": bool(skip_images),
            "caption_font": str(caption_font or "Impact"),
            "caption_font_size": int(caption_font_size),
            "caption_color": str(caption_color or "#FFFFFF"),
            "caption_stroke_color": str(caption_stroke_color or "#000000"),
            "music_dir": str(music_dir or ""),
            "music_volume_pct": float(music_volume_pct),
            "music_track": "" if not music_track or music_track == RANDOM_PICK else str(music_track),
            "smart_music_start": bool(smart_music_start),
            "sfx_dir": str(sfx_dir or ""),
            "sfx_volume_pct": float(sfx_volume_pct),
            "sfx_track": "" if not sfx_track or sfx_track == RANDOM_PICK else str(sfx_track),
        }
        if custom_script.strip():
            job["script"] = custom_script.strip()
        img_prompts = [p.strip() for p in custom_image_prompts.splitlines() if p.strip()]
        if img_prompts:
            job["image_prompts"] = img_prompts
        # uploaded files (Gradio File component returns list of file objects or paths)
        uploaded_paths: list = []
        if uploaded_images:
            for f in uploaded_images:
                if hasattr(f, "name"):
                    uploaded_paths.append(str(f.name))
                elif isinstance(f, str):
                    uploaded_paths.append(f)
        if uploaded_paths:
            job["image_paths"] = uploaded_paths
        if source_mode == "Direkt-URL":
            if not source_url.strip():
                yield log + "\nFEHLER: Direkt-URL ist leer\n", last_video
                return
            job["source_url"] = source_url.strip()
        else:
            if not channel_url.strip():
                yield log + "\nFEHLER: Kanal-URL ist leer\n", last_video
                return
            job["channel_url"] = channel_url.strip()
            kws = [k.strip() for k in title_filter.split(",") if k.strip()]
            if kws:
                job["title_filter"] = kws
            job["channel_scan_limit"] = int(channel_scan_limit)

        q: queue.Queue = queue.Queue()
        result = {"out": None, "err": None}

        def worker(job=job, q=q, result=result):
            try:
                out = run_one(job, cfg, on_step=lambda m: q.put(m))
                result["out"] = out
            except Exception as e:
                tb = traceback.format_exc()
                result["err"] = f"{type(e).__name__}: {e}\n{tb}"
            finally:
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        log += f"\n========== Short {run_i + 1}/{n}: {base_slug} ==========\n"
        yield log, last_video

        while True:
            try:
                msg = q.get(timeout=1.0)
            except queue.Empty:
                yield log, last_video
                continue
            if msg is None:
                break
            log += msg + "\n"
            yield log, last_video

        t.join(timeout=2.0)
        if result["err"]:
            log += f"\nFEHLER: {result['err']}\n"
            yield log, last_video
            continue
        last_video = str(result["out"])
        log += f"\n✓ Fertig: {result['out']}\n"
        yield log, last_video

    log += "\n========== Alle Shorts fertig ==========\n"
    yield log, last_video


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Bezys Shorts Generator") as app:
        gr.Markdown("# 🎬 Bezys Shorts Generator")
        gr.Markdown("Automatischer Pipeline-Lauf: YouTube-Download → Gemini/Llama-Skript → "
                    "ElevenLabs Voiceover → Cloudflare/Pollinations Bilder → 9:16 Schnitt mit Untertiteln.")

        with gr.Accordion("⚙️ Config-Datei", open=False):
            config_path = gr.Textbox(value="config.json", label="Pfad zur config.json")

        # ───────────── Video-Quelle ─────────────
        with gr.Accordion("📺 Video-Quelle", open=True):
            source_mode = gr.Radio(
                ["Kanal scrapen", "Direkt-URL"],
                value="Kanal scrapen",
                label="Modus",
            )
            with gr.Group() as channel_group:
                channel_url = gr.Textbox(
                    value="https://www.youtube.com/@DopeGameplays/videos",
                    label="YouTube-Kanal-URL",
                )
                title_filter = gr.Textbox(
                    value="roblox, doors, blox fruits, brookhaven, tower of hell, obby, blox, evade, adopt me, jailbreak, bedwars, piggy",
                    label="Titel-Filter (Stichwörter, kommagetrennt — mindestens eines muss matchen)",
                )
                channel_scan_limit = gr.Slider(
                    30, 500, value=200, step=10,
                    label="Channel-Tiefe (wie viele letzte Videos im Pool)",
                )
            with gr.Group(visible=False) as url_group:
                source_url = gr.Textbox(
                    value="",
                    label="YouTube-Video-URL",
                    placeholder="https://www.youtube.com/watch?v=...",
                    interactive=True,
                )

        # ───────────── Skript & Stimme ─────────────
        with gr.Accordion("🎤 Skript & Stimme", open=True):
            topic = gr.Textbox(
                value="Krasser Moment, totaler Wahnsinn",
                label="Skript-Thema",
                lines=2,
                info="Gemini/Llama schreibt daraus das Skript zur Ziel-Länge",
            )
            custom_script = gr.Textbox(
                value="",
                label="Eigenes Skript (optional, überschreibt Thema)",
                lines=5,
                placeholder="Wenn ausgefüllt, wird das hier 1:1 als Sprechertext genommen — kein LLM-Call.",
            )
            with gr.Row():
                target_duration = gr.Slider(
                    15, 120, value=30, step=1,
                    label="Ziel-Länge (Sekunden)",
                )
                clip_segments = gr.Slider(
                    1, 24, value=1, step=1,
                    label="Anzahl Szenen-Cuts",
                    info="1 = ein Stück, mehr = Highlight-Reel",
                )
            smart_picking = gr.Checkbox(
                value=False,
                label="🔊 Smart Scene-Picking (laute Stellen im Source-Video finden)",
                info="Analysiert die Audio-Lautstärke und schneidet rund um die Peaks (~+10s Analyse pro Video)",
            )
            voice_id = gr.Dropdown(
                choices=VOICES,
                value=VOICES[0][1],
                label="ElevenLabs Stimme",
            )

        # ───────────── Audio (BGM + SFX) ─────────────
        with gr.Accordion("🎵 Audio (Musik + SFX)", open=False):
            with gr.Tab("🎶 Hintergrundmusik"):
                music_dir = gr.Textbox(
                    value=r"C:\Users\bezy\Desktop\music",
                    label="Hintergrundmusik-Ordner",
                    info="MP3/WAV-Dateien hier rein. Leer oder leerer Ordner = keine Musik.",
                )
                with gr.Row():
                    music_track = gr.Dropdown(
                        choices=list_music_tracks(r"C:\Users\bezy\Desktop\music"),
                        value=RANDOM_PICK,
                        label="Track",
                        info="Wähle eine Datei oder lass auf Zufällig",
                        scale=4,
                    )
                    music_refresh = gr.Button("🔄", scale=1)
                music_volume_pct = gr.Slider(
                    0, 30, value=5, step=1,
                    label="Hintergrundmusik Lautstärke (%)",
                    info="Quadratisch skaliert — 3% ist quasi unhörbar, 10% sehr leise, 30% deutlich.",
                )
                smart_music_start = gr.Checkbox(
                    value=True,
                    label="🎯 Smart Music Start (lauteste Stelle / Drop finden)",
                    info="Analysiert den Track und startet nicht zwingend bei 0:00, sondern wo es richtig losgeht. +2–5s pro Track.",
                )
            with gr.Tab("💥 Sound-Effects"):
                sfx_dir = gr.Textbox(
                    value=r"C:\Users\bezy\Desktop\sfx",
                    label="Sound-Effects-Ordner",
                    info="MP3/WAV-Dateien (Whoosh, Ding, Boom etc.) — werden bei jedem Bild-Pop-In abgespielt.",
                )
                with gr.Row():
                    sfx_track = gr.Dropdown(
                        choices=list_music_tracks(r"C:\Users\bezy\Desktop\sfx"),
                        value=RANDOM_PICK,
                        label="SFX-Datei",
                        info="Zufällig pickt pro Bild eine andere Datei aus dem Ordner",
                        scale=4,
                    )
                    sfx_refresh = gr.Button("🔄", scale=1)
                sfx_volume_pct = gr.Slider(
                    0, 100, value=40, step=1,
                    label="SFX Lautstärke (%)",
                )

        # ───────────── Bild-Overlays ─────────────
        with gr.Accordion("🖼️ Bild-Overlays", open=True):
            with gr.Row():
                image_count = gr.Slider(1, 5, value=3, step=1, label="Anzahl Bilder")
                image_duration = gr.Slider(0.8, 3.0, value=1.5, step=0.1, label="Bild-Dauer (Sekunden)")
            custom_image_prompts = gr.Textbox(
                value="",
                label="Eigene Bild-Prompts (optional, eine Zeile pro Bild)",
                lines=4,
                placeholder=(
                    "z.B.\n"
                    "vertical cartoon, character mid-jump, neon colors\n"
                    "vertical cartoon, monster chase scene, dramatic lighting\n"
                    "vertical cartoon, victory pose, confetti, vibrant colors"
                ),
                info="Leer = LLM erzeugt aus dem Skript. Weniger Zeilen als Bilder = Rest wird auto-generiert.",
            )
            uploaded_images = gr.File(
                file_count="multiple",
                file_types=["image"],
                label="Eigene Bilder hochladen (überschreibt Auto-Generierung komplett)",
            )
            skip_images = gr.Checkbox(value=False, label="Bilder komplett überspringen")

        # ───────────── Untertitel ─────────────
        with gr.Accordion("🎨 Untertitel-Einstellungen", open=False):
            caption_font = gr.Dropdown(
                choices=[
                    ("Impact", "Impact"),
                    ("Arial-Bold", "Arial Black"),
                    ("Verdana", "Verdana"),
                ],
                value="Impact",
                label="Schriftart",
            )
            with gr.Row():
                caption_color = gr.ColorPicker(value="#FFFF00", label="Textfarbe")
                caption_stroke_color = gr.ColorPicker(value="#000000", label="Randfarbe (Stroke)")
            caption_font_size = gr.Slider(
                30, 90, value=60, step=1,
                label="Schriftgröße",
            )

        # ───────────── Batch ─────────────
        with gr.Accordion("🔁 Batch", open=False):
            batch_count = gr.Slider(1, 10, value=1, step=1, label="Anzahl Shorts hintereinander")

        generate_btn = gr.Button("🎬 Short generieren", variant="primary", size="lg")

        with gr.Row():
            status_log = gr.Textbox(
                label="Status-Log",
                lines=20,
                max_lines=40,
                interactive=False,
            )

        video_out = gr.Video(label="Fertiger Short", autoplay=False)

        def toggle_source(mode: str):
            is_channel = mode == "Kanal scrapen"
            return (
                gr.update(visible=is_channel),
                gr.update(visible=not is_channel),
            )

        source_mode.change(
            toggle_source,
            inputs=[source_mode],
            outputs=[channel_group, url_group],
        )

        def _refresh_tracks(folder: str):
            return gr.update(choices=list_music_tracks(folder), value=RANDOM_PICK)

        music_dir.change(_refresh_tracks, inputs=[music_dir], outputs=[music_track])
        music_refresh.click(_refresh_tracks, inputs=[music_dir], outputs=[music_track])
        sfx_dir.change(_refresh_tracks, inputs=[sfx_dir], outputs=[sfx_track])
        sfx_refresh.click(_refresh_tracks, inputs=[sfx_dir], outputs=[sfx_track])

        generate_btn.click(
            generate,
            inputs=[
                config_path, source_mode, source_url, channel_url, title_filter,
                channel_scan_limit, topic, custom_script, target_duration,
                clip_segments, smart_picking, voice_id, music_dir, music_track, music_volume_pct,
                smart_music_start,
                sfx_dir, sfx_track, sfx_volume_pct,
                image_count, image_duration, custom_image_prompts, uploaded_images,
                skip_images,
                caption_font, caption_color, caption_stroke_color, caption_font_size,
                batch_count,
            ],
            outputs=[status_log, video_out],
        )

    return app


if __name__ == "__main__":
    app = build_app()
    # Gradio 6 sandboxes file delivery; let it serve videos from the user's home
    allowed = [str(Path.home())]
    port = find_free_port()
    print(f"Starte GUI auf http://127.0.0.1:{port}")
    try:
        app.launch(server_name="127.0.0.1", server_port=port, inbrowser=True,
                   theme=gr.themes.Soft(), allowed_paths=allowed)
    except TypeError:
        app.launch(server_name="127.0.0.1", server_port=port, inbrowser=True,
                   allowed_paths=allowed)
