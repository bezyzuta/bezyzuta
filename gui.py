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

from pipeline import Config, run_one, run_multiclip


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


# Chatterbox TTS (Resemble AI) is voice-clone-based instead of fixed-voice.
# No voice dropdown — either the user picks a reference audio file to clone,
# or the model's built-in default voice is used.


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")
    return s or "short"


def generate(
    output_format: str,
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
    playback_speed: float,
    scene_pick_mode: str,
    manual_ranges: str,
    auto_reframe: bool,
    reframe_v2: bool,
    reframe_samples_per_seg: int,
    speaker_detection: bool,
    enable_voice: bool,
    tts_language: str,
    tts_piper_model: str,
    voice_ref_audio: str,
    tts_exaggeration: float,
    tts_cfg_weight: float,
    enable_music: bool,
    music_dir: str,
    music_track: str,
    music_volume_pct: int,
    smart_music_start: bool,
    enable_sfx: bool,
    sfx_dir: str,
    sfx_track: str,
    sfx_volume_pct: int,
    enable_captions: bool,
    image_count: int,
    image_duration: float,
    custom_image_prompts: str,
    uploaded_images,
    skip_images: bool,
    caption_font: str,
    caption_color: str,
    caption_stroke_color: str,
    caption_font_size: int,
    hook_text: str,
    hook_duration: float,
    pop_captions: bool,
    progress_bar: bool,
    subscribe_overlay: bool,
    subscribe_sting_file: str,
    subscribe_sting_volume: int,
    whisper_device: str,
    multiclip_enabled: bool,
    multiclip_count: int,
    batch_count: int,
    resume_enabled: bool,
    log_level: str,
    youtube_metadata: bool,
    youtube_thumbnail: bool,
    youtube_lang: str,
):
    log = ""
    try:
        cfg = Config.load(Path(config_path))
        cfg.tts_reference_audio = (voice_ref_audio or "").strip()
        cfg.tts_exaggeration = float(tts_exaggeration)
        cfg.tts_cfg_weight = float(tts_cfg_weight)
        cfg.tts_language = (tts_language or "auto").lower()
        cfg.tts_piper_model = (tts_piper_model or "de_DE-thorsten-medium").strip()
        # Apply orientation toggle: override target_w/target_h on cfg so the
        # whole pipeline (crop, scale, captions, overlays) follows. Config
        # file values are ignored when this flag is set, which is the
        # intended behavior — the GUI is the source of truth.
        if (output_format or "portrait").lower() == "landscape":
            cfg.target_w, cfg.target_h = 1920, 1080
        else:
            cfg.target_w, cfg.target_h = 1080, 1920
    except Exception as e:
        yield f"Config-Fehler: {e}", None
        return

    last_video = None
    n = max(1, int(batch_count))

    for run_i in range(n):
        base_slug = slugify(topic)
        if n > 1:
            base_slug = f"{base_slug}-{run_i + 1}"

        # When resume is OFF, the user wants a fresh render. Auto-suffix the
        # slug if a folder or final mp4 with the same name already exists, so
        # we never collide with a previous run's artifacts (which would
        # otherwise overwrite/confuse). When resume IS on, the slug stays
        # stable on purpose — that's how resume finds the cached state.
        if not resume_enabled:
            try:
                out_root = Path(Config.load(Path(config_path)).output_dir).expanduser()
                candidate = base_slug
                counter = 2
                while (out_root / candidate).exists() or (out_root / f"{candidate}.mp4").exists():
                    candidate = f"{base_slug}-{counter}"
                    counter += 1
                base_slug = candidate
            except Exception:
                # If output_dir isn't resolvable yet, fall back to base_slug —
                # pipeline.py will raise a clearer error downstream.
                pass

        job = {
            "slug": base_slug,
            "topic": topic,
            "target_duration": float(target_duration),
            "clip_segments": int(clip_segments),
            "playback_speed": float(playback_speed),
            "scene_pick_mode": str(scene_pick_mode or "even"),
            "manual_ranges": str(manual_ranges or ""),
            "auto_reframe": bool(auto_reframe),
            "reframe_v2": bool(reframe_v2),
            "reframe_samples_per_seg": int(reframe_samples_per_seg),
            "speaker_detection": bool(speaker_detection),
            "resume": bool(resume_enabled),
            "log_level": str(log_level or "INFO"),
            "youtube_metadata": bool(youtube_metadata),
            "youtube_thumbnail": bool(youtube_thumbnail),
            "youtube_lang": str(youtube_lang or "auto"),
            "enable_voice": bool(enable_voice),
            "image_count": int(image_count),
            "image_duration": float(image_duration),
            "no_image": bool(skip_images),
            "caption_font": str(caption_font or "Impact"),
            "caption_font_size": int(caption_font_size),
            "caption_color": str(caption_color or "#FFFFFF"),
            "caption_stroke_color": str(caption_stroke_color or "#000000"),
            "hook_text": str(hook_text or "").strip(),
            "hook_duration": float(hook_duration),
            "pop_captions": bool(pop_captions),
            "progress_bar": bool(progress_bar),
            "subscribe_overlay": bool(subscribe_overlay),
            "subscribe_sting_file": str(subscribe_sting_file or "").strip(),
            "subscribe_sting_volume": float(subscribe_sting_volume),
            "whisper_device": str(whisper_device or "auto"),
            "multiclip_enabled": bool(multiclip_enabled),
            "multiclip_count": int(multiclip_count),
            "enable_music": bool(enable_music),
            "music_dir": str(music_dir or ""),
            "music_volume_pct": float(music_volume_pct),
            "music_track": "" if not music_track or music_track == RANDOM_PICK else str(music_track),
            "smart_music_start": bool(smart_music_start),
            "enable_sfx": bool(enable_sfx),
            "enable_captions": bool(enable_captions),
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
                if bool(job.get("multiclip_enabled")):
                    outs = run_multiclip(job, cfg, on_step=lambda m: q.put(m))
                    result["out"] = outs[-1] if outs else None
                    result["outs"] = outs
                else:
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
        last_video = str(result["out"]) if result.get("out") else last_video
        if result.get("outs"):
            log += f"\n✓ Multi-Clip fertig: {len(result['outs'])} Shorts erstellt:\n"
            for p in result["outs"]:
                log += f"    {p}\n"
        else:
            log += f"\n✓ Fertig: {result['out']}\n"
        yield log, last_video

    log += "\n========== Alle Shorts fertig ==========\n"
    yield log, last_video


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Bezys Shorts Generator") as app:
        gr.Markdown("# 🎬 Bezys Shorts Generator")
        gr.Markdown("Automatischer Pipeline-Lauf: YouTube-Download → Gemini/Llama-Skript → "
                    "Chatterbox-TTS Voiceover → Cloudflare/Pollinations Bilder → Schnitt mit Untertiteln.")

        # ───────────── Output-Format ─────────────
        # First-class toggle at the top: the rest of the pipeline reads
        # this from job["output_format"] and uses it to set cfg.target_w /
        # cfg.target_h before run_one / run_multiclip dispatches. Long-mode
        # additionally relaxes the duration cap and skips reframe work.
        output_format = gr.Radio(
            choices=[
                ("📱 Short — 9:16 Hochformat (1080×1920)", "portrait"),
                ("🎬 Lang-Video — 16:9 Querformat (1920×1080)", "landscape"),
            ],
            value="portrait",
            label="🖼️ Output-Format",
            info=("Hochformat = YouTube/TikTok-Short, schmaler vertikaler Crop, "
                  "Auto-Reframe wirkt. Querformat = normales YouTube-Video, "
                  "kein Crop, Auto-Reframe wird ignoriert."),
        )

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
            enable_voice = gr.Checkbox(
                value=True,
                label="🎙️ Sprecher aktiv",
                info=("Aus = kein Voiceover, keine TTS-Generierung, keine Untertitel. "
                      "Video läuft nur mit Musik/SFX/Bildern. Skript-Thema und TTS-Optionen darunter werden ignoriert."),
            )
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
                    15, 900, value=30, step=1,
                    label="Ziel-Länge (Sekunden)",
                    info="Shorts: 15-60s. Lang-Videos: bis 900s (15 min). Über 60s = kein YouTube-Short mehr.",
                )
                clip_segments = gr.Slider(
                    1, 24, value=1, step=1,
                    label="Anzahl Szenen-Cuts",
                    info="1 = ein Stück, mehr = Highlight-Reel",
                )
                playback_speed = gr.Slider(
                    0.5, 1.5, value=1.0, step=0.05,
                    label="🎚️ Wiedergabe-Geschwindigkeit",
                    info=("Wird nach dem Compose über das fertige Video gelegt. "
                          "1.0 = normal, 1.1 = 10% schneller, 1.25 = deutlich schneller, "
                          "0.9 = leicht entschleunigt. Bild + Ton bleiben synchron."),
                )
            scene_pick_mode = gr.Radio(
                choices=[("Standard — gleichmäßig verteilt", "even"),
                         ("🔊 Laute Stellen — Audio-Peaks (~+10s)", "loud"),
                         ("🤖 KI-Auswahl — Gemini Vision wählt spannendste Szenen (~+15s)", "ai"),
                         ("✂️ Manuell — Zeiten selber angeben", "manual")],
                value="even",
                label="Szenen-Auswahl",
                info="KI-Modus extrahiert Thumbnails und lässt Gemini die action-geladensten picken. "
                     "Manuell: du gibst exakte Zeit-Bereiche vor.",
            )
            manual_ranges = gr.Textbox(
                value="",
                label="Manuelle Zeit-Bereiche (eine Zeile pro Szene)",
                lines=6,
                placeholder=(
                    "Format: START-END pro Zeile (MM:SS oder HH:MM:SS oder Sekunden)\n\n"
                    "1:18-1:25\n"
                    "2:35-2:45\n"
                    "5:10-5:22\n"
                    "12:30-12:45"
                ),
                info='Beispiele: "1:18-1:25" (M:SS), "0:01:30-0:01:45" (H:MM:SS), "78-85" (Sekunden). '
                     'Die ausgewählten Bereiche werden in der Reihenfolge zusammen­geschnitten. '
                     'Ziel-Länge und Anzahl Szenen-Cuts werden ignoriert wenn dieser Modus aktiv ist.',
                visible=False,
            )
            auto_reframe = gr.Checkbox(
                value=False,
                label="🎯 Auto-Reframe (KI findet wo Menschen/Gesichter sind)",
                info=("Für Querformat-Videos mit Personen seitlich (Dokus, Interviews). "
                      "Statt mittig zu croppen, schiebt der 9:16-Ausschnitt sich zu den Subjekten. "
                      "Braucht Cloudflare-Credentials. ~+5s pro Video."),
            )
            with gr.Row():
                reframe_v2 = gr.Checkbox(
                    value=False,
                    label="⚡ Auto-Reframe v2 (stabiler, mit Smoothing + Multi-Face)",
                    info=("Verbesserter Algorithmus: pro Segment 3 Samples, konfidenz-gewichtete "
                          "Aggregation, zeitliches Smoothing (kein Frame-Sprung bei einer "
                          "Fehlerkennung), Multi-Face-Awareness für Podcasts. Nur wirksam wenn "
                          "Auto-Reframe oben angehakt ist."),
                )
                reframe_samples_per_seg = gr.Slider(
                    1, 7, value=3, step=1,
                    label="Samples pro Segment (v2)",
                    info="Mehr Samples = stabiler, aber langsamer. 3 ist der Sweet Spot.",
                )
            speaker_detection = gr.Checkbox(
                value=False,
                label="🎤 Active Speaker Detection (Crop folgt wer gerade redet)",
                info=("Für Podcasts mit ≥2 Personen: pro Segment wird per MediaPipe-FaceMesh "
                      "die Mundöffnung jedes Gesichts gemessen — wer den Mund am offensten "
                      "hat = aktiver Speaker, dorthin wird gecroppt. Wechselt automatisch "
                      "wenn der andere zu reden anfängt. Braucht Reframe v2."),
            )
            tts_language = gr.Dropdown(
                choices=[
                    ("Auto (Skript=DE, TTS aus Text erkennen)", "auto"),
                    ("🇩🇪 Deutsch (Gemini schreibt DE → Piper TTS)", "de"),
                    ("🇬🇧 Englisch (Gemini schreibt EN → Chatterbox TTS)", "en"),
                ],
                value="auto",
                label="🌍 Sprache (Skript + TTS)",
                info=("Steuert sowohl den Gemini-Prompt als auch die TTS-Engine. "
                      "DE → Gemini schreibt deutsch, Piper spricht (lokal, ~63 MB, schnell). "
                      "EN → Gemini schreibt englisch, Chatterbox spricht (GPU, Voice-Cloning möglich). "
                      "Sicherheits-Override: wenn dein Custom-Script in der anderen Sprache ist, "
                      "wird die richtige Engine automatisch gewählt."),
            )
            tts_piper_model = gr.Dropdown(
                choices=[
                    ("Thorsten — DE, männlich, medium (empfohlen)", "de_DE-thorsten-medium"),
                    ("Thorsten — DE, männlich, high (langsamer, etwas besser)", "de_DE-thorsten-high"),
                    ("Eva K. — DE, weiblich, x_low (klein, simpel)", "de_DE-eva_k-x_low"),
                ],
                value="de_DE-thorsten-medium",
                label="Piper Voice (nur bei DE)",
                info="Wird beim ersten Lauf automatisch aus huggingface gezogen und gecacht.",
            )
            gr.Markdown(
                "**Chatterbox TTS (Englisch):** erster Run lädt ~3GB Modell. "
                "Optional: Voice-Sample-Datei für eigene Stimme klonen."
            )
            voice_ref_audio = gr.Textbox(
                value="",
                label="🎤 Voice-Sample für Cloning (optional, .wav/.mp3 — nur EN)",
                placeholder=r"z.B. C:\Users\bezy\Desktop\voices\meine_stimme.wav",
                info=("5-10 Sekunden saubere Aufnahme der Stimme die geklont werden "
                      "soll. Leer = Chatterbox' Default-Stimme. Wirkt nur bei englischen Skripts."),
            )
            with gr.Row():
                tts_exaggeration = gr.Slider(
                    0.0, 1.0, value=0.5, step=0.05,
                    label="Chatterbox Emotion (nur EN)",
                    info="0 = ruhig/flach, 0.5 = neutral, 1 = dramatisch. Für Shorts: 0.6-0.8 funktioniert gut.",
                )
                tts_cfg_weight = gr.Slider(
                    0.0, 1.0, value=0.5, step=0.05,
                    label="Chatterbox CFG Weight (nur EN)",
                    info="Niedriger = natürlicheres Sprachtempo, höher = wörtlicher.",
                )

        # ───────────── Audio (BGM + SFX) ─────────────
        with gr.Accordion("🎵 Audio (Musik + SFX)", open=False):
            with gr.Tab("🎶 Hintergrundmusik"):
                enable_music = gr.Checkbox(
                    value=True,
                    label="Hintergrundmusik aktiv",
                    info="Aus = kein BGM, egal was unten eingestellt ist.",
                )
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
                enable_sfx = gr.Checkbox(
                    value=True,
                    label="Sound-Effects aktiv",
                    info="Aus = keine SFX bei Bild-Pop-ins oder Szenen-Cuts.",
                )
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

        # ───────────── Hook ─────────────
        with gr.Accordion("🪝 Hook-Overlay (großer Text am Anfang)", open=True):
            hook_text = gr.Textbox(
                value="",
                label="Hook-Text",
                lines=2,
                placeholder="z.B. POV: Du wirst nicht glauben was passiert ist...",
                info="Erscheint groß und mittig-oben für die ersten paar Sekunden. Leer = kein Hook. Mehrere Zeilen für Zeilenumbruch.",
            )
            hook_duration = gr.Slider(
                1.0, 6.0, value=3.0, step=0.5,
                label="Anzeigedauer (Sekunden)",
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

        # ───────────── Engagement-Effekte ─────────────
        with gr.Accordion("✨ Engagement-Effekte", open=True):
            pop_captions = gr.Checkbox(
                value=False,
                label="🔍 Auto-Zoom auf Untertitel (TikTok-Style)",
                info="Jedes Caption-Chunk poppt von 125% auf 100% rein — wirkt dynamischer.",
            )
            progress_bar = gr.Checkbox(
                value=False,
                label="📊 Progress-Bar unten am Video",
                info="Dünner roter Balken am unteren Bildrand der mitläuft — hält Zuschauer bis zum Ende.",
            )
            subscribe_overlay = gr.Checkbox(
                value=False,
                label="🔔 Subscribe-Button am Ende",
                info='Rotes "ABONNIEREN" Banner in den letzten 2,5 Sekunden.',
            )
            subscribe_sting_file = gr.Textbox(
                value="",
                label="🎵 Sound-Effekt zum Subscribe-Banner (optional)",
                placeholder=r"z.B. C:\Users\bezy\Desktop\sfx\bell.mp3",
                info="Wird genau dann abgespielt wenn das Banner erscheint. Leer = kein Sting.",
            )
            subscribe_sting_volume = gr.Slider(
                0, 100, value=60, step=1,
                label="Sting-Lautstärke (%)",
            )

        # ───────────── Untertitel ─────────────
        with gr.Accordion("🎨 Untertitel-Einstellungen", open=False):
            enable_captions = gr.Checkbox(
                value=True,
                label="Gesprochene Untertitel einblenden",
                info="Aus = keine Wort-für-Wort-Captions. Hook & Subscribe-Button (falls aktiv) bleiben.",
            )
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

        # ───────────── Performance ─────────────
        with gr.Accordion("⚡ Performance", open=False):
            whisper_device = gr.Radio(
                choices=[("Auto (GPU bevorzugt, fallback CPU)", "auto"),
                         ("GPU forcieren (NVIDIA CUDA)", "cuda"),
                         ("CPU forcieren (langsamer aber kompatibel)", "cpu")],
                value="auto",
                label="Whisper-Transkription auf",
                info="Mit RTX-Karte: 5-10x schneller als CPU. Erstmaliger GPU-Start lädt CUDA-Libs (~3s extra).",
            )

        # ───────────── Batch ─────────────
        # ───────────── Multi-Clip ─────────────
        with gr.Accordion("🎬 Multi-Clip-Modus (1 Source → N Shorts)", open=False):
            multiclip_enabled = gr.Checkbox(
                value=False,
                label="Multi-Clip aktiv",
                info=("Whisper transkribiert das ganze Source-Video, Gemini findet "
                      "automatisch die viralsten Momente, jeder wird als eigener Short "
                      "gerendert. Plus Titel/Hashtags/Virality-Score je Clip als .txt. "
                      "Nur mit Direkt-URL als Source. Überschreibt die normale Batch."),
            )
            multiclip_count = gr.Slider(
                2, 15, value=5, step=1,
                label="Anzahl Clips aus dem Source-Video",
                info="Gemini pickt diese Anzahl der besten Momente.",
            )

        with gr.Accordion("🔁 Batch (gleiches Setup, mehrere Random-Picks)", open=False):
            batch_count = gr.Slider(1, 10, value=1, step=1, label="Anzahl Shorts hintereinander")

        # ───────────── Resume & Logging ─────────────
        with gr.Accordion("🔄 Resume & Logging", open=False):
            resume_enabled = gr.Checkbox(
                value=False,
                label="♻️ Resume aktiv (Job kann unterbrochen + fortgesetzt werden)",
                info=("Speichert nach jedem Pipeline-Schritt einen Checkpoint in "
                      "{output_dir}/{slug}/job_state.json. Beim nächsten Lauf mit "
                      "gleichem Slug werden fertige Schritte (Download, Transkription, "
                      "Voiceover, Bilder, …) NICHT neu gemacht. Multi-Clip: pro Sub-Clip "
                      "separater Checkpoint — abgebrochenes Multi-Clip läuft genau dort "
                      "weiter wo's gecrashed ist."),
            )
            log_level = gr.Dropdown(
                choices=["DEBUG", "INFO", "WARN", "ERROR"],
                value="INFO",
                label="Log-Level",
                info="DEBUG zeigt jede Detector-Entscheidung. WARN versteckt Routine-Infos.",
            )

        # ───────────── YouTube Optimizer ─────────────
        with gr.Accordion("📈 YouTube Optimizer (Title / Description / Tags / Thumbnail)", open=False):
            youtube_metadata = gr.Checkbox(
                value=False,
                label="📝 YouTube-Metadaten generieren",
                info=("Erstellt für jeden fertigen Short eine .youtube.json + .youtube.txt "
                      "mit Titel (max 100 Z.), Beschreibung (mit #Shorts), 8-15 Tags und "
                      "Thumbnail-Prompt. Gemini wird zuerst versucht, Cloudflare Llama als "
                      "Fallback, sonst Template. Kein direkter Upload — Sidecar-Files sind "
                      "zum Copy-Paste in den YouTube-Studio."),
            )
            with gr.Row():
                youtube_thumbnail = gr.Checkbox(
                    value=True,
                    label="🖼️ Thumbnail-Bild dazu generieren",
                    info="Erzeugt zusätzlich {slug}_thumb.png via Cloudflare Flux / Pollinations.",
                )
                youtube_lang = gr.Dropdown(
                    choices=[("Auto (Skript-Sprache übernehmen)", "auto"),
                             ("Deutsch", "de"), ("Englisch", "en")],
                    value="auto",
                    label="Sprache für Metadaten",
                )

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

        def toggle_manual_ranges(mode: str):
            return gr.update(visible=(mode == "manual"))

        scene_pick_mode.change(
            toggle_manual_ranges,
            inputs=[scene_pick_mode],
            outputs=[manual_ranges],
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
                output_format,
                config_path, source_mode, source_url, channel_url, title_filter,
                channel_scan_limit, topic, custom_script, target_duration,
                clip_segments, playback_speed, scene_pick_mode, manual_ranges, auto_reframe,
                reframe_v2, reframe_samples_per_seg, speaker_detection,
                enable_voice, tts_language, tts_piper_model,
                voice_ref_audio, tts_exaggeration, tts_cfg_weight,
                enable_music, music_dir, music_track, music_volume_pct,
                smart_music_start,
                enable_sfx, sfx_dir, sfx_track, sfx_volume_pct,
                enable_captions,
                image_count, image_duration, custom_image_prompts, uploaded_images,
                skip_images,
                caption_font, caption_color, caption_stroke_color, caption_font_size,
                hook_text, hook_duration,
                pop_captions, progress_bar, subscribe_overlay,
                subscribe_sting_file, subscribe_sting_volume,
                whisper_device,
                multiclip_enabled, multiclip_count,
                batch_count,
                resume_enabled, log_level,
                youtube_metadata, youtube_thumbnail, youtube_lang,
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
