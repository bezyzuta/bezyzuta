"""Gradio GUI on top of pipeline.run_one. Run: python gui.py"""

import queue
import re
import socket
import sys
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
    use_claude_cli: bool,
    claude_cli_model: str,
    source_mode: str,
    source_url: str,
    channel_url: str,
    title_filter: str,
    channel_scan_limit: int,
    topic: str,
    custom_script: str,
    extend_script: bool,
    target_duration: float,
    clip_segments: int,
    playback_speed: float,
    voice_tempo: float,
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
    normalize_audio: bool,
    target_lufs: float,
    enable_sfx: bool,
    sfx_dir: str,
    sfx_track: str,
    sfx_volume_pct: int,
    enable_captions: bool,
    image_count: int,
    image_duration: float,
    image_size: float,
    image_vpos: float,
    image_style: str,
    custom_image_prompts: str,
    uploaded_images,
    skip_images: bool,
    image_tilt: bool,
    images_continuous: bool,
    export_timestamp_images: bool,
    image_change_secs: float,
    image_gap_secs: float,
    image_allow_photos: bool,
    image_allow_videos: bool,
    caption_font: str,
    caption_color: str,
    caption_stroke_color: str,
    caption_font_size: int,
    caption_position: str,
    hook_text: str,
    hook_duration: float,
    effects_enabled: list,
    effects_ai: bool,
    pop_captions: bool,
    caption_emojis: bool,
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
    youtube_thumb_from_video: bool,
    youtube_lang: str,
):
    log = ""
    try:
        cfg = Config.load(Path(config_path))
        # Only override the config's voice sample when the GUI field is
        # filled — otherwise keep whatever tts_reference_audio is set in
        # config.json, so a permanently-configured clone voice "just works"
        # without re-typing the path every run.
        _gui_voice = (voice_ref_audio or "").strip()
        if _gui_voice:
            cfg.tts_reference_audio = _gui_voice
        cfg.tts_exaggeration = float(tts_exaggeration)
        cfg.tts_cfg_weight = float(tts_cfg_weight)
        cfg.tts_language = (tts_language or "auto").lower()
        cfg.tts_piper_model = (tts_piper_model or "de_DE-thorsten-medium").strip()
        # Apply orientation toggle: override target_w/target_h on cfg so the
        # whole pipeline (crop, scale, captions, overlays) follows. Config
        # file values are ignored when this flag is set, which is the
        # intended behavior — the GUI is the source of truth.
        _fmt = (output_format or "portrait").lower()
        if _fmt == "landscape":
            cfg.target_w, cfg.target_h = 1920, 1080
        else:  # portrait or faceless
            cfg.target_w, cfg.target_h = 1080, 1920
        # Faceless Story preset: hand-drawn style (unless the user explicitly
        # picked a non-auto style) + continuous per-beat images.
        _faceless = _fmt == "faceless"
        # Claude-CLI provider toggle (overrides config.json for this run).
        cfg.use_claude_cli = bool(use_claude_cli)
        if claude_cli_model is not None:
            cfg.claude_cli_model = str(claude_cli_model).strip()
        # Image-style picker (overrides config.json for this run). Empty/None
        # keeps whatever's in config.json.
        if image_style:
            cfg.image_style = str(image_style).strip()
        # Faceless format forces a hand-drawn style unless the user already
        # picked a flat one — default to MS-Paint stickman.
        if _faceless and (cfg.image_style or "auto").lower() not in ("ms_paint_stickman", "doodle_sketch"):
            cfg.image_style = "ms_paint_stickman"
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
            "voice_tempo": float(voice_tempo),
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
            "youtube_thumb_from_video": bool(youtube_thumb_from_video),
            "youtube_lang": str(youtube_lang or "auto"),
            "enable_voice": bool(enable_voice),
            "image_count": int(image_count),
            "image_duration": float(image_duration),
            "image_size": float(image_size),
            "image_vpos": float(image_vpos),
            "no_image": bool(skip_images),
            "image_tilt": bool(image_tilt),
            # Faceless format forces continuous per-beat images; otherwise honor
            # the checkbox.
            "images_continuous": bool(images_continuous) or _faceless,
            "export_timestamp_images": bool(export_timestamp_images),
            "image_change_secs": float(image_change_secs),
            "image_gap_secs": float(image_gap_secs),
            "image_allow_photos": bool(image_allow_photos),
            "image_allow_videos": bool(image_allow_videos),
            "caption_font": str(caption_font or "Impact"),
            "caption_font_size": int(caption_font_size),
            "caption_color": str(caption_color or "#FFFFFF"),
            "caption_stroke_color": str(caption_stroke_color or "#000000"),
            "caption_position": str(caption_position or "top"),
            "hook_text": str(hook_text or "").strip(),
            "hook_duration": float(hook_duration),
            "effects_enabled": list(effects_enabled or []),
            "effects_ai": bool(effects_ai),
            "pop_captions": bool(pop_captions),
            "caption_emojis": bool(caption_emojis),
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
            "normalize_audio": bool(normalize_audio),
            "target_lufs": float(target_lufs),
            "enable_sfx": bool(enable_sfx),
            "enable_captions": bool(enable_captions),
            "sfx_dir": str(sfx_dir or ""),
            "sfx_volume_pct": float(sfx_volume_pct),
            "sfx_track": "" if not sfx_track or sfx_track == RANDOM_PICK else str(sfx_track),
        }
        if custom_script.strip():
            job["script"] = custom_script.strip()
            job["extend_script"] = bool(extend_script)
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


def _config_defaults(config_path: str = "config.json") -> dict:
    """Read a few fields from config.json at GUI-build time so form fields
    can be pre-filled (e.g. the clone-voice path). Best-effort: returns {}
    if the file is missing or unreadable."""
    try:
        cfg = Config.load(Path(config_path))
        return {
            "tts_reference_audio": getattr(cfg, "tts_reference_audio", "") or "",
            "tts_exaggeration": getattr(cfg, "tts_exaggeration", 0.5),
            "tts_cfg_weight": getattr(cfg, "tts_cfg_weight", 0.5),
            "tts_language": getattr(cfg, "tts_language", "auto") or "auto",
        }
    except Exception:
        return {}


_CUSTOM_CSS = """
.gradio-container { max-width: 1080px !important; margin: 0 auto !important; }
#hero {
  background: linear-gradient(120deg, #7c3aed 0%, #db2777 50%, #f97316 100%);
  border-radius: 18px; padding: 22px 26px; margin-bottom: 14px;
  box-shadow: 0 8px 30px rgba(124,58,237,.35);
}
#hero h1 { color:#fff; margin:0; font-size:30px; font-weight:800; letter-spacing:.3px; }
#hero p  { color:#f3e8ff; margin:6px 0 0; font-size:14px; }
.gr-accordion { box-shadow: 0 2px 10px rgba(0,0,0,.06); margin-bottom: 8px !important; border-radius:14px !important; }
#go_btn button, #go_btn {
  font-size:19px !important; font-weight:800 !important; padding:16px !important;
  border-radius:14px !important; border:none !important; color:#fff !important;
  background: linear-gradient(120deg, #f97316, #db2777) !important;
}
#go_btn button:hover { filter: brightness(1.07); }
"""


def _theme():
    try:
        return gr.themes.Soft(
            primary_hue="orange", secondary_hue="violet", neutral_hue="slate",
            font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        )
    except Exception:
        return gr.themes.Soft()


def build_app() -> gr.Blocks:
    _defaults = _config_defaults()
    # NOTE: theme + css are applied at launch() time (see main()). Gradio 6
    # moved them off the Blocks constructor; passing them here only warns.
    with gr.Blocks(title="Bezys Shorts Generator") as app:
        gr.HTML(
            '<div id="hero">'
            '<h1>🎬 Bezys Shorts Generator</h1>'
            '<p>YouTube-Download → KI-Skript → geklonte Stimme → cinematische Bilder + Memes → '
            'fertiger Short mit Untertiteln, Emojis & SFX</p>'
            '</div>'
        )

        # ───────────── Output-Format ─────────────
        # First-class toggle at the top: the rest of the pipeline reads
        # this from job["output_format"] and uses it to set cfg.target_w /
        # cfg.target_h before run_one / run_multiclip dispatches. Long-mode
        # additionally relaxes the duration cap and skips reframe work.
        output_format = gr.Radio(
            choices=[
                ("📱 Short — 9:16 Hochformat (1080×1920)", "portrait"),
                ("🎬 Lang-Video — 16:9 Querformat (1920×1080)", "landscape"),
                ("📝 Faceless Story — 9:16, handgezeichneter Stil", "faceless"),
            ],
            value="portrait",
            label="🖼️ Output-Format",
            info=("Hochformat = YouTube/TikTok-Short, schmaler vertikaler Crop, "
                  "Auto-Reframe wirkt. Querformat = normales YouTube-Video, "
                  "kein Crop. Faceless = Story-Video im Danny-Why-Stil "
                  "(Strichmännchen/Doodle, durchgehende Bilder) — setzt Bild-Stil "
                  "+ Optionen automatisch."),
        )

        with gr.Accordion("⚙️ Config-Datei", open=False):
            config_path = gr.Textbox(value="config.json", label="Pfad zur config.json")

        # ───────────── KI-Modell (lokale Claude CLI) ─────────────
        with gr.Accordion("🧠 KI-Modell — Claude statt Gemini (lokal, Abo)", open=False):
            gr.Markdown(
                "Nutzt die lokal installierte **Claude Code CLI** (dein Abo, kein API-Key, "
                "keine Extra-Kosten) statt Gemini für die Text-Aufgaben — vor allem das "
                "**Moment-Picking** (dein größter Qualitäts-Schmerzpunkt). "
                "Langsamer als Gemini und zählt gegen deine Abo-Limits. "
                "Bei Fehler/CLI-fehlt → automatischer Fallback auf Gemini. "
                "Nur für lokalen Privatgebrauch gedacht."
            )
            use_claude_cli = gr.Checkbox(
                value=False,
                label="🧠 Claude CLI für Text-Aufgaben nutzen (Moment-Picking, Skript, Metadaten)",
                info="Voraussetzung: 'claude' CLI installiert und eingeloggt (claude login).",
            )
            claude_cli_model = gr.Dropdown(
                choices=[
                    ("Standard (was die CLI gerade nutzt)", ""),
                    ("Sonnet — schnell + sehr gut (empfohlen)", "sonnet"),
                    ("Opus — beste Qualität, mehr Abo-Verbrauch", "opus"),
                    ("Haiku — am schnellsten, schwächer", "haiku"),
                ],
                value="sonnet",
                label="Claude-Modell",
                info="Für Moment-Picking lohnt sich Sonnet oder Opus — beide deutlich besser als Gemini Flash.",
            )

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
                placeholder=("Wenn ausgefüllt, wird das hier 1:1 als Sprechertext genommen — kein LLM-Call. "
                             "Tipp: NICHT die Antwort eines Chatbots reinkopieren (Zeilen wie "
                             "'Here is the script for you:' würden mitgesprochen) — nur den reinen Skript-Text."),
            )
            extend_script = gr.Checkbox(
                value=False,
                label="🪶 Skript per AI verlängern wenn zu kurz",
                info=("Wenn dein eigenes Skript deutlich kürzer ist als Ziel-Länge: Gemini "
                      "schreibt automatisch eine Fortsetzung im selben Stil. Standard AUS — "
                      "dein Skript bleibt sonst exakt wie geschrieben."),
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
                voice_tempo = gr.Slider(
                    0.7, 1.2, value=1.0, step=0.05,
                    label="🗣️ Sprechtempo (nur Stimme)",
                    info=("Nur die Stimme, Tonhöhe bleibt gleich. 1.0 = normal, "
                          "0.85 = ruhiger (gut für lange Videos), 0.9 = leicht "
                          "langsamer. Für Shorts 1.0 lassen."),
                )
            with gr.Accordion("🎬 Szenen-Auswahl", open=False):
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
                value=_defaults.get("tts_language", "auto"),
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
                "Optional: eigene Stimme klonen.\n\n"
                "**🎙️ Stimme klonen — so geht's:**\n"
                "1. Nimm **10–15 Sekunden** deiner Stimme auf (Handy-Sprachmemo oder PC) — "
                "ruhig sprechen, **kein Hintergrundgeräusch/Musik**, ein durchgehender Satz.\n"
                "2. Datei (.wav/.mp3/.m4a — auch ein Video geht) hier unten eintragen.\n"
                "3. Die Pipeline **säubert das Sample automatisch** (mono, Stille raus, ~12s, "
                "normalisiert) — du musst nichts schneiden. Das geklonte `.clone.wav` wird daneben gecacht.\n"
                "4. **Sprache auf Englisch** stellen (Cloning wirkt nur über Chatterbox)."
            )
            voice_ref_audio = gr.Dropdown(
                choices=[
                    ("— Chatterbox Default-Stimme (kein Cloning) —", ""),
                    ("Besmir (clone.wav, aufbereitet)", r"C:\Users\bezy\Desktop\Agenten\voice.clone.wav"),
                    ("Besmir (Rohaufnahme besmir.wav)", r"C:\Users\bezy\Desktop\Agenten\besmir.wav"),
                ],
                value=_defaults.get("tts_reference_audio", ""),
                allow_custom_value=True,
                label="🎤 Stimme zum Klonen (auswählen oder Pfad eintippen — nur EN)",
                info=("Deine Klon-Stimmen zur Auswahl, oder einen beliebigen Pfad "
                      "eintippen. '.clone.wav' wird direkt genutzt, eine Rohaufnahme "
                      "wird automatisch aufbereitet. Vorbefüllt aus config.json. "
                      "Leer = Chatterbox' Default-Stimme."),
            )
            with gr.Row():
                tts_exaggeration = gr.Slider(
                    0.0, 1.0, value=_defaults.get("tts_exaggeration", 0.5), step=0.05,
                    label="Chatterbox Emotion (nur EN)",
                    info="0 = ruhig/flach, 0.5 = neutral, 1 = dramatisch. Für Shorts: 0.6-0.8 funktioniert gut.",
                )
                tts_cfg_weight = gr.Slider(
                    0.0, 1.0, value=_defaults.get("tts_cfg_weight", 0.5), step=0.05,
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
                normalize_audio = gr.Checkbox(
                    value=True,
                    label="🔊 Lautheit normalisieren (laut + konsistent wie die Profis)",
                    info="EBU-R128 loudnorm auf den fertigen Mix — so laut und gleichmäßig wie virale Shorts. Empfohlen AN.",
                )
                target_lufs = gr.Slider(
                    -16, -9, value=-14, step=1,
                    label="Ziel-Lautheit (LUFS)",
                    info="-14 = YouTube-Norm (sicher). -11 = TikTok-Punch (lauter). Niedriger = leiser.",
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
        with gr.Accordion("🪝 Hook-Overlay (großer Text am Anfang)", open=False):
            hook_text = gr.Textbox(
                value="",
                label="Hook-Text",
                lines=2,
                placeholder="z.B. POV: Du wirst nicht glauben was passiert ist...",
                info=("Erscheint groß und mittig-oben für die ersten paar Sekunden. Leer = kein Hook. "
                      "Tipp: Klick '🎣 Hooks vorschlagen' für 4 KI-Varianten zum Auswählen."),
            )
            with gr.Row():
                hook_generate_btn = gr.Button("🎣 Hooks vorschlagen", scale=1)
                hook_picker = gr.Radio(choices=[], value=None,
                                       label="Vorschläge (Klick zum Übernehmen)",
                                       scale=3, interactive=True)

            def _gen_hooks(topic_v, lang_v, cfg_path_v, use_claude_v, claude_model_v):
                try:
                    cfg = Config.load(Path(cfg_path_v))
                    cfg.use_claude_cli = bool(use_claude_v)
                    if claude_model_v is not None:
                        cfg.claude_cli_model = str(claude_model_v).strip()
                    lang = (lang_v or "auto").lower()
                    if lang not in ("de", "en"):
                        lang = "de"
                    from pipeline import generate_hook_variants
                    hooks = generate_hook_variants(topic_v or "", cfg, n=4, language=lang)
                except Exception as e:
                    hooks = [f"(Fehler: {str(e)[:60]})"]
                return gr.update(choices=hooks, value=None)

            hook_duration = gr.Slider(
                1.0, 6.0, value=3.0, step=0.5,
                label="Anzeigedauer (Sekunden)",
            )

        # ───────────── Bild-Overlays ─────────────
        with gr.Accordion("🖼️ Bild-Overlays", open=False):
            with gr.Row():
                image_count = gr.Slider(1, 50, value=3, step=1, label="Anzahl Bilder")
                image_duration = gr.Slider(0.8, 5.0, value=1.5, step=0.1, label="Bild-Dauer (Sekunden)")
            with gr.Row():
                image_size = gr.Slider(
                    0.5, 1.0, value=1.0, step=0.02,
                    label="📐 Bild-Größe (Breite)",
                    info="Anteil der Bildbreite. 1.0 = volle Breite (empfohlen), 0.85 = kleiner.",
                )
                image_vpos = gr.Slider(
                    -0.25, 0.25, value=-0.03, step=0.01,
                    label="↕️ Bild vertikal (− hoch / 0 Mitte / + runter)",
                    info="0 = genau Mitte. Negativ schiebt nach oben, positiv nach unten.",
                )
            image_style = gr.Dropdown(
                choices=[
                    ("🤖 Auto — KI wählt pro Bild (Roblox-Render / fotoreal)", "auto"),
                    ("🧱 Roblox — alle Bilder als 3D-Roblox-Render", "roblox"),
                    ("📷 Realistisch — fotorealistisch, kein Roblox", "realistic"),
                    ("🎞️ Cinematisch — Film-Still-Look", "cinematic"),
                    ("✏️ MS-Paint Strichmännchen (Faceless-Style)", "ms_paint_stickman"),
                    ("✒️ Doodle / Sketch (Faceless-Style)", "doodle_sketch"),
                ],
                value="auto",
                label="🎨 Bild-Stil",
                info=("Wie alle KI-Bilder aussehen. 'Auto' = pro Beat passend. "
                      "Die Faceless-Styles (Strichmännchen/Doodle) sind für "
                      "Explainer-/Story-Videos im Danny-Why-Stil."),
            )
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
            image_tilt = gr.Checkbox(
                value=False,
                label="↪️ Bilder leicht schräg kippen (Tilt)",
                info=("An = verspielter Tilt-Look. Aus = gerade Rechtecke wie bei den "
                      "Top-Roblox-Shorts (empfohlen). Bild-Stil ist jetzt cinematischer "
                      "3D-Roblox-Render statt flacher Cartoon."),
            )
            images_continuous = gr.Checkbox(
                value=True,
                label="🖼️ Durchgehend wechselnde Bilder in der Mitte (wie im Referenz-Video)",
                info=("An = pro gesprochenem Beat ein eigenes, passendes Bild — wechselt "
                      "alle paar Sekunden, lückenlos. Anzahl wird automatisch aus der Länge "
                      "berechnet (Bild-Anzahl-Slider wird dann ignoriert). Nur Hochformat."),
            )
            export_timestamp_images = gr.Checkbox(
                value=False,
                label="🗂️ Bilder zusätzlich nach Zeitstempel exportieren (für CapCut)",
                info=("Legt parallel zum fertigen Video alle generierten Bilder in einen "
                      "Ordner '<slug>_timestamp_images' — benannt nach ihrer Einblende-Zeit "
                      "(00_07.png, 00_15.png …), wie im Danny-Why-Workflow. Du kannst sie "
                      "dann manuell in CapCut auf die Timeline ziehen."),
            )
            image_change_secs = gr.Slider(
                1.0, 6.0, value=3.5, step=0.5,
                label="⏱️ Sekunden pro Bild (bei durchgehend)",
                info="Wie oft das Mittelbild wechselt. 3-4s wie im Referenz-Video.",
            )
            image_gap_secs = gr.Slider(
                0.0, 1.5, value=0.5, step=0.1,
                label="⏸️ Pause zwischen Bildern (Sek)",
                info=("Kurze Lücke nur mit Gameplay, bevor das nächste Bild kommt. "
                      "Das Bild startet weiterhin genau auf seinem Wort. 0 = nahtlos."),
            )
            image_allow_photos = gr.Checkbox(
                value=True,
                label="📷 Auch echte Fotos verwenden (free via Openverse, kein KI)",
                info=("An = Mix aus KI-Roblox-Renders UND echten lizenzfreien Fotos, die zum "
                      "Text passen (geschockte Person, Geldstapel, Pokal …) — wie virale Shorts. "
                      "Die KI entscheidet pro Beat was besser passt. Aus = nur KI-Bilder."),
            )
            image_allow_videos = gr.Checkbox(
                value=False,
                label="📹 Auch Stock-VIDEOS verwenden (Pexels B-Roll, KOSTENLOS mit Key)",
                info=("An = bei passenden Beats werden echte kurze Stock-Clips eingeblendet "
                      "(rennen, Geld zählen, Explosion, Stadt bei Nacht …). Erfordert "
                      "pexels_api_key in config.json (https://www.pexels.com/api/ — 30s, kostenlos). "
                      "Massiver Qualitätssprung. Bei Fehler → Foto/KI-Fallback."),
            )

        # ───────────── Engagement-Effekte ─────────────
        with gr.Accordion("✨ Engagement-Effekte", open=False):
            gr.Markdown("**🎬 KI-Effekt-Regie** — wähle erlaubte Effekte, die KI (Claude/Gemini) "
                        "entscheidet dann WANN/WO sie im Video kommen.")
            effects_enabled = gr.CheckboxGroup(
                choices=[
                    ("🎨 Viral Color-Grade (Sättigung/Kontrast/Vignette)", "color_grade"),
                    ("⚪ Flash (weißer Blitz bei Schock/Reveal)", "flash"),
                    ("📳 Camera-Shake (Wackeln bei Impact-Momenten)", "shake"),
                    ("👊 Punch-In (schneller Zoom-Stoß zur Betonung)", "punch"),
                    ("🔎 Ken-Burns (Mittel-Bilder zoomen langsam)", "ken_burns"),
                    ("➡️ Slide-In (Bilder fliegen von der Seite rein)", "slide_in"),
                    ("💬 Keyword-Pop (Untertitel-Wort flasht gelb bei Schlüsselwort)", "keyword_pop"),
                    ("🎤 Per-Wort-Karaoke (TikTok-Style: ein Wort nach dem anderen, mit Pop)", "word_karaoke"),
                    ("🩸 Horror: Roter Blitz (Jumpscare/Gefahr)", "red_flash"),
                    ("🌑 Horror: Dunkel-Puls (Bedrohung/Licht geht aus)", "dark_pulse"),
                    ("📺 Horror: Glitch (übernatürlich/etwas stimmt nicht)", "glitch"),
                    ("🫣 Horror: Creep-Zoom (langsam schleichende Anspannung)", "creep"),
                    ("🎬 Horror: Color-Grade (kalt, entsättigt, dunkle Vignette)", "horror_grade"),
                ],
                value=[],
                label="Effekte erlauben (leer = aus)",
                info=("Color-Grade/Horror-Grade/Ken-Burns/Slide-In/Keyword-Pop gelten global. "
                      "Flash/Shake/Punch und die Horror-Effekte (Roter Blitz/Dunkel-Puls/"
                      "Glitch/Creep-Zoom) setzt die KI an die passenden Stellen im Skript."),
            )
            effects_ai = gr.Checkbox(
                value=True,
                label="🤖 KI bestimmt Timing (aus statt → gleichmäßig verteilt)",
                info="An: Claude/Gemini liest das Skript und platziert Flash/Shake an den krassesten Momenten.",
            )
            pop_captions = gr.Checkbox(
                value=False,
                label="🔍 Auto-Zoom auf Untertitel (TikTok-Style)",
                info="Jedes Caption-Chunk poppt von 125% auf 100% rein — wirkt dynamischer.",
            )
            caption_emojis = gr.Checkbox(
                value=True,
                label="😱 Kontext-Emojis unter den Untertiteln",
                info=("Wie bei viralen Roblox-Shorts: passendes Emoji unter der Caption "
                      "wenn ein Schlüsselwort auftaucht (💰 bei Geld, ⚠️ bei Warnung, "
                      "😱 bei Schock). Nur bei Treffer, nicht bei jeder Zeile."),
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
            caption_position = gr.Dropdown(
                choices=[
                    ("Oben — über den Bildern (wie virale Roblox-Shorts)", "top"),
                    ("Mitte", "center"),
                    ("Unten", "bottom"),
                ],
                value="top",
                label="📍 Untertitel-Position",
                info="Oben = Text sitzt über dem Bild in der Mitte, wie im Referenz-Video. Bei Lang-Videos immer unten.",
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
                caption_color = gr.ColorPicker(value="#FFFFFF", label="Textfarbe")
                caption_stroke_color = gr.ColorPicker(value="#000000", label="Randfarbe (Stroke)")
            caption_font_size = gr.Slider(
                30, 90, value=80, step=1,
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
                youtube_thumb_from_video = gr.Checkbox(
                    value=True,
                    label="🎬 Thumbnail aus dem Video (Action-Frame + Hook-Text)",
                    info=("Empfohlen: nimmt einen Action-Frame aus deinem fertigen Video und "
                          "schreibt den Hook in großem gelben Impact-Text drüber — typischer "
                          "YouTube-Roblox-Thumb-Stil. Aus = klassisches KI-Thumbnail."),
                )
                youtube_lang = gr.Dropdown(
                    choices=[("Auto (Skript-Sprache übernehmen)", "auto"),
                             ("Deutsch", "de"), ("Englisch", "en")],
                    value="auto",
                    label="Sprache für Metadaten",
                )

        generate_btn = gr.Button("🎬 Short generieren", variant="primary", size="lg", elem_id="go_btn")

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

        hook_generate_btn.click(
            _gen_hooks,
            inputs=[topic, tts_language, config_path, use_claude_cli, claude_cli_model],
            outputs=[hook_picker],
        )
        # Picking a hook copies it into the hook_text field.
        hook_picker.change(lambda h: gr.update(value=h or ""),
                           inputs=[hook_picker], outputs=[hook_text])

        generate_btn.click(
            generate,
            inputs=[
                output_format,
                config_path, use_claude_cli, claude_cli_model,
                source_mode, source_url, channel_url, title_filter,
                channel_scan_limit, topic, custom_script, extend_script, target_duration,
                clip_segments, playback_speed, voice_tempo, scene_pick_mode, manual_ranges, auto_reframe,
                reframe_v2, reframe_samples_per_seg, speaker_detection,
                enable_voice, tts_language, tts_piper_model,
                voice_ref_audio, tts_exaggeration, tts_cfg_weight,
                enable_music, music_dir, music_track, music_volume_pct,
                smart_music_start, normalize_audio, target_lufs,
                enable_sfx, sfx_dir, sfx_track, sfx_volume_pct,
                enable_captions,
                image_count, image_duration, image_size, image_vpos,
                image_style,
                custom_image_prompts, uploaded_images,
                skip_images, image_tilt, images_continuous,
                export_timestamp_images,
                image_change_secs, image_gap_secs, image_allow_photos, image_allow_videos,
                caption_font, caption_color, caption_stroke_color, caption_font_size,
                caption_position,
                hook_text, hook_duration,
                effects_enabled, effects_ai,
                pop_captions, caption_emojis, progress_bar, subscribe_overlay,
                subscribe_sting_file, subscribe_sting_volume,
                whisper_device,
                multiclip_enabled, multiclip_count,
                batch_count,
                resume_enabled, log_level,
                youtube_metadata, youtube_thumbnail, youtube_thumb_from_video, youtube_lang,
            ],
            outputs=[status_log, video_out],
        )

    return app


def _preflight_config(config_path: str = "config.json") -> None:
    """Validate config.json before launching the GUI. Errors abort startup
    with a clear message; warnings print to stderr but the GUI still boots.
    Caller has already been told this can fail — we just exit(1) on errors
    so they're not chasing API-key crashes 5 minutes into a job."""
    cp = Path(config_path)
    if not cp.is_file():
        print(f"\n  ERROR: config file {cp} not found.", file=sys.stderr)
        print(f"  Copy config.example.json → config.json and fill in your keys.\n",
              file=sys.stderr)
        sys.exit(1)
    try:
        cfg = Config.load(cp)
    except Exception as e:
        print(f"\n  ERROR: config.json failed to parse: {e}\n", file=sys.stderr)
        sys.exit(1)
    errors, warnings = cfg.validate()
    for w in warnings:
        print(f"  WARN: {w}", file=sys.stderr)
    if errors:
        print("\n  Config errors prevent startup:", file=sys.stderr)
        for e in errors:
            print(f"    - {e}", file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Entry point for both `python gui.py` and the packaged .exe launcher."""
    _preflight_config()
    app = build_app()
    # Gradio 6 sandboxes file delivery; let it serve videos from the user's home
    allowed = [str(Path.home())]
    port = find_free_port()
    print(f"Starte GUI auf http://127.0.0.1:{port}")
    # Gradio 6 takes theme + css on launch() (not on Blocks). Try the
    # styled launch; fall back to a bare launch on older Gradio that
    # doesn't accept these kwargs here.
    base_kw = dict(server_name="127.0.0.1", server_port=port,
                   inbrowser=True, allowed_paths=allowed)
    try:
        app.launch(theme=_theme(), css=_CUSTOM_CSS, **base_kw)
    except TypeError:
        app.launch(**base_kw)


if __name__ == "__main__":
    main()
