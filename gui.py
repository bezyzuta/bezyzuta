"""Gradio GUI on top of pipeline.run_one. Run: python gui.py"""

import queue
import re
import threading
import time
import traceback
from pathlib import Path

import gradio as gr

from pipeline import Config, run_one


# (display label, voice_id)
VOICES = [
    ("Harry — jung, energetisch (Empfohlen für Roblox)", "SOYHLrjzK2X1ezoPC6cr"),
    ("Josh — jung, tief",                                "TxGEqnHWrfWFTfGW9XjX"),
    ("Liam — jung, conversational",                      "TX3LPaxmHKxFdv7VOQHJ"),
    ("Antoni — warm, jung",                              "ErXwobaYiN019PkySvjV"),
    ("Sam — rau, casual",                                "yoZ06aMxZJJ28mfd3POQ"),
    ("Charlie — jung, australisch",                      "IKne3meq5aSn9XLyUdCD"),
    ("Adam — tief, mature",                              "pNInz6obpgDQGcFmaJgB"),
    ("Brian — tief, narrativ",                           "nPczCjzI2devNBz1zQrb"),
    ("Daniel — britisch, news",                          "onwK4e9ZLuTAKqWW03F9"),
    ("Michael — ruhig, sympathisch",                     "flq6f7yk4E4fJM5XTYuZ"),
    ("Rachel — weiblich, klar",                          "21m00Tcm4TlvDq8ikWAM"),
    ("Domi — weiblich, stark",                           "AZnzlk1XvdvUeBnXmlld"),
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
    topic: str,
    voice_id: str,
    image_count: int,
    image_duration: float,
    skip_images: bool,
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
            "image_count": int(image_count),
            "image_duration": float(image_duration),
            "no_image": bool(skip_images),
        }
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
    with gr.Blocks(title="Roblox Shorts Generator") as app:
        gr.Markdown("# 🎬 Roblox Shorts Generator")
        gr.Markdown("Automatischer Pipeline-Lauf: YouTube-Download → Gemini-Skript → "
                    "ElevenLabs Voiceover → Pollinations Bilder → 9:16 Schnitt mit Untertiteln.")

        with gr.Accordion("⚙️ Config-Datei", open=False):
            config_path = gr.Textbox(value="config.json", label="Pfad zur config.json")

        with gr.Group():
            gr.Markdown("### 📺 Video-Quelle")
            source_mode = gr.Radio(
                ["Kanal scrapen", "Direkt-URL"],
                value="Kanal scrapen",
                label="Modus",
            )
            channel_url = gr.Textbox(
                value="https://www.youtube.com/@DopeGameplays/videos",
                label="YouTube-Kanal-URL",
                visible=True,
            )
            title_filter = gr.Textbox(
                value="roblox, doors, blox fruits, brookhaven, tower of hell, parkour",
                label="Titel-Filter (Stichwörter, kommagetrennt — mindestens eines muss matchen)",
                visible=True,
            )
            source_url = gr.Textbox(
                value="",
                label="YouTube-Video-URL",
                placeholder="https://www.youtube.com/watch?v=...",
                visible=False,
            )

        with gr.Group():
            gr.Markdown("### 🎤 Skript & Stimme")
            topic = gr.Textbox(
                value="Krasser Roblox Moment, totaler Wahnsinn",
                label="Skript-Thema",
                lines=2,
                info="Gemini schreibt daraus das 25-35s Skript",
            )
            voice_id = gr.Dropdown(
                choices=VOICES,
                value=VOICES[0][1],
                label="ElevenLabs Stimme",
            )

        with gr.Group():
            gr.Markdown("### 🖼️ Bild-Overlays")
            with gr.Row():
                image_count = gr.Slider(1, 5, value=3, step=1, label="Anzahl Bilder")
                image_duration = gr.Slider(0.8, 3.0, value=1.5, step=0.1, label="Bild-Dauer (Sekunden)")
            skip_images = gr.Checkbox(value=False, label="Bilder komplett überspringen")

        with gr.Group():
            gr.Markdown("### 🔁 Batch")
            batch_count = gr.Slider(1, 10, value=1, step=1, label="Anzahl Shorts hintereinander")

        generate_btn = gr.Button("🎬 Short generieren", variant="primary")

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
                gr.update(visible=is_channel),
                gr.update(visible=not is_channel),
            )

        source_mode.change(
            toggle_source,
            inputs=[source_mode],
            outputs=[channel_url, title_filter, source_url],
        )

        generate_btn.click(
            generate,
            inputs=[
                config_path, source_mode, source_url, channel_url, title_filter,
                topic, voice_id, image_count, image_duration, skip_images, batch_count,
            ],
            outputs=[status_log, video_out],
        )

    return app


if __name__ == "__main__":
    app = build_app()
    # Gradio 6 sandboxes file delivery; let it serve videos from the user's home
    allowed = [str(Path.home())]
    try:
        app.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                   theme=gr.themes.Soft(), allowed_paths=allowed)
    except TypeError:
        app.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                   allowed_paths=allowed)
