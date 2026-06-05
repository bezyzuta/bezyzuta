# Bezys Shorts Generator — Project State

YouTube-Shorts-Generator-Pipeline (Roblox / Podcast / langform → kurze vertikale Shorts).
Owner: Besmir / bezyzuta. Aktuell lokales Tool, Roadmap: Web-App + Mobile-App.

## Repo

- **Branch:** `claude/upgrade-roblox-autopilot-cdW3P` (active)
- Prior: `claude/youtube-shorts-roblox-setup-d13bP`
- **Working dir on user's machine:** `C:\Users\bezy\Desktop\roblox-shorts\bezyzuta`
- **Python:** 3.12, Windows venv at `.venv`
- **Entry points:** `gui.py` (Gradio web UI), `pipeline.py` (engine), `start-gui.bat`
- **New modules:** `state_manager.py` (resume), `youtube_optimizer.py` (metadata), `reframe_v2.py` (smoothed face track)

## Upgrade (Mai 2026 — Branch `claude/upgrade-roblox-autopilot-cdW3P`)

Drei große Features dazugebaut, ALLE opt-in über Job-Flags (Default-Verhalten unverändert):

### 1) Robust Resume + Advanced Logging (`state_manager.py`)
- **Wann aktiv:** GUI-Toggle "♻️ Resume aktiv" → `job["resume"] = True`
- Pro Slug wird `{output_dir}/{slug}/job_state.json` geschrieben mit
  Step-Status + Artefakt-Pfaden. Beim erneuten Lauf werden fertige Steps
  übersprungen (Artefakt-File muss noch existieren — sonst re-run).
- **Multi-Clip:** Eigener State unter `{output_dir}/{base_slug}__multiclip_work/job_state.json`.
  Pro Sub-Clip wird Status getrackt — `pending` / `done` / `failed`. Abgebrochener
  Multi-Clip läuft beim 2. Lauf nur die fehlenden weiter. Jeder Sub-Clip hat
  zusätzlich seinen eigenen run_one-State (kann mitten in Sub-Clip 7 weiter machen).
- **Logger** mit Levels DEBUG/INFO/WARN/ERROR, Timestamps, ANSI-Farben auf TTY,
  GUI bekommt weiterhin alle Zeilen über `step()` callback. GUI-Dropdown gesetzt
  Level über `job["log_level"]`.
- **Spec-Hash:** Job-Spec-Hash wird mitgespeichert; wenn User Parameter zwischen
  Läufen ändert → Warnung, aber Steps werden trotzdem wiederverwendet. Wer
  full re-render will: `job_state.json` löschen.

### 2) YouTube Optimizer (`youtube_optimizer.py`)
- **Wann aktiv:** GUI-Toggle "📝 YouTube-Metadaten generieren" → `job["youtube_metadata"] = True`
- Generiert nach `compose_short` einen `{video}.youtube.json` + `{video}.youtube.txt`
  Sidecar mit Titel (max 100 Z., wird gekappt), Description (mit `#Shorts`),
  8-15 Tags, Thumbnail-Prompt.
- **Provider-Reihenfolge:** Gemini → Cloudflare Llama 3.1 → Template-Fallback.
  Template-Fallback baut posting-ready Metadaten auch komplett ohne LLM
  (für den Fall dass beide APIs down sind — Pipeline failt nie an Metadaten).
- **Thumbnail-Bild:** optional via Cloudflare Flux / Pollinations Fallback,
  speichert als `{slug}_thumb.png`. Toggle in GUI.
- **Upload-Stub:** `upload_to_youtube()` ist implementiert (Google Data API v3 mit
  OAuth flow), aber NICHT aus GUI aufrufbar — fehlt die `google-api-python-client`
  Lib, wirft Fehler mit Install-Anweisung. Bewusst: User soll erst die Sidecars
  prüfen bevor automatisch hochgeladen wird.

### 3) Auto-Reframe v2 (`reframe_v2.py`)
- **Wann aktiv:** GUI-Toggle "⚡ Auto-Reframe v2" → `job["reframe_v2"] = True`
  (nur wirksam wenn Auto-Reframe oben auch an ist).
- Verbesserungen ggü. v1:
  - **Per-Segment auch in Single-Clip-Mode** — v1 hat über das ganze Clip
    gemittelt → Speaker der links→rechts läuft wurde mittig gecroppt mit
    beiden Rändern abgeschnitten. v2 macht immer per-Segment Timeline
    (auto auf ~3s Buckets in Single-Cut, manuell pro Cut in Multi-Cut).
  - **3 Samples pro Segment statt 1** — verhindert "no face → 0.5" bei
    Motion-Blur oder Hard-Cut auf der Sample-Stelle.
  - **Konfidenz-Gewichtung** — bigger box = mehr confidence. 20px Background-Face
    überstimmt nicht mehr den 200px Foreground-Host.
  - **Temporal Smoothing** — adjacent Segmente mit niedriger Confidence werden
    zum Vorgänger blended → kein Frame-Jitter bei einer Fehlerkennung.
  - **Multi-Face-Awareness** — Podcast-Layout (≥2 vergleichbar-große Gesichter)
    zieht den Crop näher zur Mitte statt das größte Face an den Rand zu jagen.
  - **Hold-Last für no-face Segmente** — Speaker dreht kurz weg → bleibt
    auf der letzten guten Position, statt nach Mitte zu springen.
- Detector-Kaskade unverändert (YOLOv11 → InsightFace → MediaPipe), v2 importiert
  lazy aus pipeline.py.

### GUI-Änderungen (`gui.py`)
- Neuer Toggle "⚡ Auto-Reframe v2" + Slider "Samples pro Segment (v2)" unter
  bestehendem Auto-Reframe.
- Neue Accordion "🔄 Resume & Logging" (Resume + Log-Level).
- Neue Accordion "📈 YouTube Optimizer" (Metadaten + Thumbnail + Sprache).

### Job-Dict-Felder (neu)
```
"resume": bool                  # checkpointing aktiv
"log_level": "DEBUG"|"INFO"|"WARN"|"ERROR"
"reframe_v2": bool              # smoothed v2 algorithm
"reframe_samples_per_seg": int  # 1-7, default 3
"speaker_detection": bool       # MAR-based active-speaker switching (needs reframe_v2)
"youtube_metadata": bool        # generate sidecar
"youtube_thumbnail": bool       # generate thumb image too
"youtube_lang": "auto"|"de"|"en"
```

### Follow-up fixes (after user-reported issues with multi-clip output)
- **Dedupe**: 70% overlap threshold → 50% (was letting near-duplicate clips through)
- **Auto-cap n_clips**: for sources < n_clips × 60s we cap to `int(src_dur / 60)` so
  Gemini can't be asked for 5 distinct moments from a 60s video.
- **2-pass hook generation**: after `_snap_and_dedupe_moments`, every moment's
  hook/title/hashtags are regenerated via `_gemini_rewrite_hook` using ONLY the
  exact post-snap range text — eliminates the "hook describes a different part
  of the video" hallucination from single-pass Gemini.
- **Speaker detection**: opt-in `job["speaker_detection"]` (needs reframe_v2 on).
  Adds MediaPipe-FaceMesh per-frame MAR (mouth-aspect-ratio) measurement; multi-
  face frames prefer the face with the noticeably highest MAR over the largest
  face, so the crop chases whoever is currently talking.
- **Gemini 2.5 Pro option**: new optional `Config.gemini_moments_model` field.
  Defaults to `gemini_model`; set to `"gemini-2.5-pro"` in config.json to get
  noticeably better viral-moment picks (uses more free-tier quota).

### Step-Constants (`state_manager.Step`)
Single: download, script, voiceover, scene_pick, transcribe, captions,
images, audio_mix (currently not checkpointed — fast), reframe, compose,
youtube_metadata
Multi: multi_download, multi_transcribe, multi_moments, multi_render

## Features (Stand: aktuell aktiv)

### Video-Quelle
- Direkt-URL (yt-dlp) ODER Channel-Scrape mit Title-Filter
- Source-File-Cache für Multi-Clip

### LLM-Provider (Text-Aufgaben)
- Standard: Gemini 2.5 Flash (Skript, Moment-Picking, Metadaten).
- **Opt-in: lokale Claude Code CLI** via `cfg.use_claude_cli` (GUI-Toggle
  "🧠 KI-Modell" + config.json). `claude_cli_complete()` ruft `claude -p
  --output-format json` per subprocess, Prompt über **stdin** (Windows
  argv-Limit!). Nutzt Abo-Auth, kein API-Key. `_complete_text()` ist der
  Dispatcher: Claude-first wenn aktiv, sonst Gemini; bei jedem CLI-Fehler
  automatischer Gemini-Fallback. Verdrahtet in Moment-Picking (Hauptgewinn),
  Skript-Generierung und Continuation. `claude_cli_model` → `--model`
  (sonnet/opus/haiku). Nur für lokalen Gebrauch — Web-App braucht echte API.

### Skript & Stimme
- **Dual-Engine TTS, sprach-gesteuert via `cfg.tts_language`** ("de" /
  "en" / "auto"). `synthesize_voiceover()` dispatcht zwischen den beiden:
  - **Englisch → Chatterbox TTS** (Resemble AI, Apache 2.0, lokal GPU).
    Zero-shot voice cloning via reference audio file (5-10s sample).
    ~3GB Model-Download bei first run, ~3-4GB VRAM resident.
    Cache: `_CHATTERBOX_MODEL` module-level singleton.
  - **Deutsch → Piper TTS** (rhasspy/piper, MIT, lokal CPU/GPU).
    Default-Voice `de_DE-thorsten-medium` (Thorsten Müller, deutscher
    Linguist, ~63 MB .onnx). Native deutsche Prosodie, real-time auf CPU,
    kein VRAM-Bedarf, kein Voice-Cloning (feste Stimmen).
    Cache: `_PIPER_VOICE` module-level + Files in `~/.cache/piper-voices/`.
    Auto-Download via `_download_piper_voice()` aus huggingface
    (rhasspy/piper-voices repo).
  - **Auto-Mode**: `_detect_language()` Heuristik (Umlaute = DE, sonst
    deutsche Stopword-Ratio > 10% = DE, sonst EN).
- Gemini 2.5 Flash für Skript-Generierung aus Topic
- Cloudflare Llama 3.1 8B als Skript-Fallback
- Template-Skript als letzter Fallback
- **Sprecher aus-Toggle**: keine Voice → silent base track

### Szenen-Auswahl (Radio)
- Standard: gleichmäßig verteilt
- Loud: Audio-Peaks via ffmpeg astats
- KI-Auswahl: Gemini Vision picks aus Thumbnails (Cloudflare Vision als Fallback)
- **Manuell**: User gibt Zeit-Bereiche ein (MM:SS-MM:SS)

### Multi-Clip (Opus-Style)
- Voll-Transkript via Whisper (subprocess-isoliert wegen cuDNN-crashes)
- **NEU `9a60c7a`**: Transkript wird in N Regionen gechunked, je 1 Gemini-Call pro
  Region → erzwungene Distribution über das ganze Video
- Snap-to-Sentence-Boundary für saubere Cuts (gewichtet: gap > punctuation)
- Dedupe bei >70% Range-Overlap
- Hard rails: 20s min, 600s (10 min) max — sonst Opus-style freie Länge
- Pro Clip: separate Source-Audio-Transkription für Captions (subprocess-isoliert)

### Auto-Reframe (3-stufige Detector-Kaskade)
1. **YOLOv11-face** via ultralytics (auf RTX 3080 ~5ms/Frame) — primary
2. **InsightFace** wenn installiert (Windows: VC++ Build Tools nötig) — fallback
3. **MediaPipe** Face Detection — final fallback, immer da
- Per-Segment in Multi-Cut, 10 Samples + Median in Single-Cut
- "Kein Gesicht erkannt" → bleibt mittig (kein LLM-Halluzinations-Fallback)
- Mapping `_subject_pct_to_crop_offset`: 10→0%, 30→15%, 50→50%, 70→85%, 90→100%

### Visual / Audio Effekte
- Hintergrundmusik mit Smart-Start (lauteste Stelle finden via astats)
- **Loudness-Normalisierung** (`normalize_loudness`, EBU R128 loudnorm) auf den
  fertigen Mix, Default-Ziel −14 LUFS. Job-Flags `normalize_audio` / `target_lufs`.
- Sound-Effects pro Bild-Pop-In + pro Scene-Cut
- Subscribe-Sting (Sound bei Subscribe-Banner)
- Hook-Overlay (großer Text oben am Anfang, manuell)
- Pop-Captions (TikTok-Style Karaoke), **Position via `caption_position`**
  (top/center/bottom; Default `top` = Text über den Mittel-Bildern wie im
  Referenz-Video; Lang-Videos immer unten)
- **Kontext-Emojis unter Captions** (`caption_emojis`, Keyword→Emoji-Heuristik
  `_CAPTION_EMOJI_KEYWORDS`, DE+EN, nur bei Treffer). **Farbig** als PNG-Overlay
  (`get_emoji_png` rendert via Pillow + System-Emoji-Font lokal, kein Netz;
  libass würde nur s/w rendern → deshalb `emoji_overlay`-Pfad in `compose_short`).
- **Durchgehend wechselnde Mittel-Bilder** (`images_continuous`): pro Sprech-Beat
  ein eigenes Bild, wechselt alle `image_change_secs` (~3.5s), Anzahl auto aus
  Voice-Länge. `_image_schedule(continuous=True)` reiht lückenlos. Nur Hochformat.
- **Bild-Quellen-Mix** (`generate_scene_plan`): LLM (Claude/Gemini) plant pro Beat
  `source=ai|photo`. AI → Flux/Pollinations (cinematischer Roblox-Render).
  photo → `fetch_free_photo` = Openverse → Wikimedia Commons (free, kein Key,
  thematisch passend), AI als Fallback. Toggle `image_allow_photos`.
- Progress-Bar unten via color+scale+overlay
- Subscribe-Button am Ende
- **Image-Overlays — cinematischer 3D-Roblox-Render-Stil** (`_IMAGE_STYLE_SUFFIX`,
  charakter-fokussiert, dramatisches Licht) statt flacher Cartoons. Scene-Prompts
  (`SCENE_PROMPT`) sind an den gesprochenen Beat gekoppelt. Tilt optional
  (`image_tilt`, Default gerade/aus). Cloudflare Flux + Pollinations Fallback.

### Whisper
- faster-whisper auf CUDA (RTX 3080) mit subprocess-Isolation für lange Runs
- nvidia-cublas/cudnn/cuda-runtime wheels für Windows installiert

## Configs

`config.json` (NICHT `config.example.json`!):
- tts_language ("de"/"en"/"auto") + tts_piper_model (default `de_DE-thorsten-medium`)
- tts_reference_audio (optional path for voice cloning, EN only) / tts_exaggeration / tts_cfg_weight
- gemini_api_key (frischer Free-Tier Account, 1500 RPD)
- cloudflare_account_id + cloudflare_api_token
- output_dir: `C:\Users\bezy\Desktop\Youtube`
- whisper_model: meist "base" oder "small"

## APIs / Services

| Wofür | Wer | Status |
|---|---|---|
| Skript-Generierung | Gemini 2.5 Flash | aktiv |
| Bild-Prompts | Gemini → Cloudflare Llama 3.1 | aktiv |
| TTS Voiceover (EN) | Chatterbox TTS (Resemble AI, local GPU) | aktiv |
| TTS Voiceover (DE) | Piper TTS (rhasspy, lokal CPU, Thorsten Voice) | aktiv |
| Vision (Scene-Picking) | Gemini Vision → Cloudflare Llama 3.2 11B Vision | aktiv |
| Face Detection | YOLOv11-face (lokal) → MediaPipe | aktiv |
| Image Generation | Cloudflare Flux Schnell | aktiv |
| Transcription | Whisper (faster-whisper) lokal | aktiv |

## Lokale Pakete

In `.venv` installiert:
- `mediapipe`, `ultralytics`, `torch+cu124`, `torchvision`, `torchaudio`
- `nvidia-cublas-cu12`, `nvidia-cudnn-cu12<10`, `nvidia-cuda-runtime-cu12`, `nvidia-cuda-nvrtc-cu12`
- `faster-whisper`, `requests`, `yt-dlp`, `gradio`
- Coqui-TTS / Ollama wurden früher installiert, dann wieder entfernt
- ElevenLabs → Edge-TTS → **Chatterbox TTS** (current). Chatterbox läuft
  lokal auf der GPU, Voice-Cloning via reference audio, ~3-4GB VRAM, sync API.
  Needs `chatterbox-tts` und `torchaudio` aus pip.

## Bekannte Limitationen / TODO

### Was NICHT perfekt funktioniert
- **Gemini's Moment-Auswahl ist mediokre verglichen mit Opus.pro**. Selbst mit
  Chunking pickt es nicht zuverlässig die wirklich viralen Momente. Liegt am
  Modell — Opus hat eigenes Trainingsmodell auf viralen Videos.
- **Auto-Reframe vergisst der User regelmäßig anzuhaken** → Clips mittig
  gecroppt. Es gibt eine dicke Warnung im Log, aber Checkbox bleibt manuell.
- **Subscribe-Sting** funktioniert, aber timing kann ±1s drift haben.

### Roadmap (vom User definiert)

User will Richtung Production: Web-App + Mobile-App. Beginnt Geld in APIs +
Server zu investieren.

Schritte vermutlich nötig:
1. Pipeline server-fähig machen (Job-Queue, Docker, GPU-Server)
2. React/Next.js Frontend statt Gradio
3. User-Auth + Billing (Stripe)
4. Direkt-Upload zu YouTube/TikTok via APIs
5. Eventuell custom Vision-Modell trainieren (für besseres Moment-Picking)

## Aktuelle offene Probleme

- **Multi-Clip-Qualität**: ohne custom trained model bleibt das deutlich
  schlechter als Opus.pro. Chunking ist eingebaut aber Gemini wählt trotzdem
  manchmal mittelmäßige Momente. Mit Claude CLI (Sonnet/Opus) als Provider
  spürbar besser, aber langsamer.
- **CLAUDE.md** ist dieser Datei (gerade von Claude geschrieben).
- Token-Verbrauch im Chat fast bei 1M — User wechselt zu frischem Chat.

## Session 2 (Mai/Juni 2026 — selbe Branch, große Quality-Welle)

Seit der letzten CLAUDE.md sind ~50 weitere Features/Fixes dazu gekommen.
Kurz-Index der wichtigsten:

### Neue LLM-Backends
- **Claude Code CLI als optionaler Provider** (`use_claude_cli` in config /
  GUI-Accordion "🧠 KI-Modell"). `claude_cli_complete()` ruft `claude -p
  --output-format json` per subprocess, **Prompt über stdin** (Windows
  argv-Limit!). `_resolve_claude_cli()` probt PATH + npm-Standardspots
  (`%APPDATA%\npm\claude.cmd` etc.), cached den vollen Pfad — Windows
  startet keine bare "claude.cmd" ohne resolved path. `_complete_text()`
  ist der Dispatcher: Claude-first wenn aktiv, sonst Gemini; bei jedem
  CLI-Fehler automatischer Fallback. Verdrahtet in:
  Moment-Picking (Hauptgewinn), Skript-Gen, Continuation, Effekt-Regie,
  Scene-Plan, Hook-Vorschläge, YouTube-Metadaten.
- Gemini Long-Form-Skript: separater Prompt für ≥90s, Top-Up-Loop (3x)
  wenn Output zu kurz, realistischere wps-Ranges (`_WPS_EN`/`_WPS_DE`).
- **YouTube cookies** (`youtube_cookies_from_browser`/`youtube_cookies_file`)
  + actionable error hints (`_ytdlp_error_hint`) gegen die "Sign in to
  confirm you're not a bot"-Wall.

### TTS: Voice-Cloning + Auto-Prep
- **Chatterbox Auto-Sample-Prep** (`prepare_voice_sample`): User gibt
  beliebige Aufnahme (Handy-Memo, Video) als `tts_reference_audio` an,
  Pipeline macht ffmpeg → mono 24k, Stille raus, ~12s gekappt, normalize.
  Cache als `<name>.clone.wav` neben dem Original; nur neu wenn Source
  jünger. Datei die bereits `.clone.wav` heißt wird direkt genutzt.
  GUI-Feld pre-fillt sich aus config.json; leeres GUI-Feld überschreibt
  config NICHT mehr (User muss Pfad nicht jedes Mal eintragen).

### Bild-Pipeline — komplette Überholung
- **Per-Beat Scene-Plan** (`generate_scene_plan`): LLM plant pro
  gesprochenem Beat `source=ai|photo|video`. Anzahl Bilder wird aus
  Voice-Länge auto-bestimmt (`image_change_secs`, Default 3.5s; 4..14
  cap). Continuous-Schedule: Bild startet **auf** seinem Wort, endet
  `image_gap` (0.5s) vor dem nächsten — nahtlos verkettet aber mit
  Gameplay-Atempausen.
- **Cinematischer 3D-Roblox-Render-Stil** statt flacher Cartoons
  (`_IMAGE_STYLE_SUFFIX`). Scene-Prompts an gesprochenen Beat gekoppelt
  ("a rich Roblox avatar with crown..." statt generisch).
- **Bild-Größe + Position als Slider** (`image_size` 0.92 Default,
  `image_vpos` -0.03 Default = fast Mitte). Tilt optional, Default aus
  (gerade Rechtecke).
- **Bild-Quellen-Kaskade** (`fetch_free_photo` mit Process-wide
  Circuit-Breaker `_DISABLED_PHOTO_SOURCES`):
  **Pexels** (`pexels_api_key`, free, beste Qualität) →
  **Pixabay** (`pixabay_api_key`, free) →
  **Openverse** (kein Key) → **Wikimedia** (kein Key) → AI-Fallback.
  Quota-Fehler (429/403/"rate limit"/"quota") disablen die Quelle für
  den Rest des Runs (keine wiederholten slow-failing calls).
- **Pexels Videos** (`fetch_video_from_pexels`, selber Key): Stock-B-Roll
  in der Mitte statt Standbild. Eigene `_video_chain` (kein -loop, kein
  Tilt/Pop, fade in/out, weißer Rand). compose_short routet pro Beat
  zu `_image_chain` oder `_video_chain` basierend auf Suffix
  (.mp4 = video, sonst image). Opt-in via `image_allow_videos`.
- **Twemoji/Pillow Color-Emoji-Overlays** statt libass-mono. `get_emoji_png`
  rendert lokal mit Segoe UI Emoji / Noto Color Emoji, kein Netz. Position
  passt sich Caption-Position an: Caption oben → Emoji unter Caption,
  Caption unten → Emoji **über** Caption (sonst landet's hinter dem Bild).
  Funktioniert in jeder Orientierung (Hoch + Quer).

### Audio
- **Loudness-Normalisierung** (`normalize_loudness`, EBU R128) auf finalen
  Mix, Default -14 LUFS (`target_lufs` slider -16..-9).
- **SFX synchron zum Bildwechsel** (Fix: SFX-Schedule nutzt jetzt denselben
  continuous-Flag wie der Bild-Schedule — vorher lief SFX ~1s versetzt).

### Caption-Styling
- **Position via `caption_position`** ("top"/"center"/"bottom"). Default
  "top" (über Mittelbildern wie Referenz-Video). Long-Form forciert "bottom".
- **Per-Wort-Karaoke** (`word_karaoke` in effects): ein Wort pro Dialogue
  mit gelb→weiß Pop (TikTok-Style). Long-Form ausgenommen.
- **Keyword-Pop** (`keyword_pop`): Caption-Chunk mit Trigger-Wort
  (`_CAPTION_EMOJI_KEYWORDS`) wird kurz größer + gelb.
- **Long-Form-Captions** (≥landscape): 8-Wort-Chunks statt 3-Wort-Pop,
  Original-Case statt ALL-CAPS, anchored bottom.
- Default Textfarbe `#FFFFFF`, Default Schriftgröße `80`.

### Effekte (KI-Regie) — `generate_effect_plan`
- CheckboxGroup `effects_enabled` mit 7 Optionen + `effects_ai` (Default
  on): LLM platziert die timed Effekte (flash/shake/punch) an dramatische
  Skript-Stellen. Globals: `color_grade`, `ken_burns` (Mittelbilder driften
  +6% Zoom), `slide_in` (Mittelbilder fliegen rein), `keyword_pop`,
  `word_karaoke`.
- `_effects_final_vf` baut die ffmpeg-Filter-Chain (shake → eq+vignette
  → drawbox-flash → punch-zoom), wird nach dem ganzen Compose appliziert.
- Speed-Ramp/Freeze-Frame **bewusst NICHT** drin — würde die Voice/
  Caption-Timeline desynchronisieren.

### YouTube Optimizer
- **Long-Form-aware** Metadata-Prompts (Portrait/Landscape getrennt).
- **Chapter-Markers** auto generiert (`generate_chapters`), per
  `_format_chapter_timestamp` mit YouTube-Regeln (erste = 0:00, ≥10s
  Abstand, ≥3 chapters).
- **Thumbnail-from-Video** (`generate_thumbnail_from_video`,
  `youtube_thumb_from_video`): Pickt Action-Frame aus erster Hälfte
  (höchste stddev), Pillow malt Hook in gelbem Impact + schwarzem Outline
  + Bottom-Gradient — typischer Roblox-YouTube-Thumb-Stil. AI-Thumb als
  Fallback.

### GUI
- Modernes Theme (Orange/Violett + Inter-Font), Custom-CSS Hero-Header,
  großer Gradient-Button "🎬 Short generieren" (`elem_id=go_btn`),
  Karten-Optik für Accordions. **Theme/CSS bei `launch()`** (Gradio 6).
- **Output-Format-Toggle ganz oben**: Short 9:16 / Long-Video 16:9 (setzt
  `cfg.target_w/target_h`, schaltet auto-reframe in Landscape ab,
  forciert bottom-captions, erweitert target_duration auf 900s).
- **Wiedergabe-Geschwindigkeit**-Slider (0.5..1.5, ffmpeg setpts+atempo
  Post-Compose). **Image-Gap**-Slider (0..1.5s), **Bild-Größe** + **Bild-vpos**.
- **Sprache (Skript+TTS)** Dropdown: auto/de/en. Steuert sowohl Gemini-
  Prompt-Sprache als auch TTS-Engine (Piper bei DE, Chatterbox bei EN).
  Bidirektionaler Safety-Override: wenn Custom-Script in anderer Sprache
  ist als Toggle, switcht automatisch.
- **🎣 Hook-Vorschläge-Button** (`generate_hook_variants`, n=4):
  LLM gibt 4 Hook-Varianten, Radio → Klick füllt `hook_text` Feld.
- **Pre-fill aus config.json** (`_config_defaults`): tts_reference_audio,
  tts_language, tts_exaggeration, tts_cfg_weight beim GUI-Start.
- Szenen-Auswahl in eigenes eingeklapptes Accordion.

### Code-Hygiene
- **185 grüne pytest Tests** in `tests/` (pure functions, scene_plan,
  effects, captions, claude_cli mit subprocess-Mock, config-validate,
  youtube_chapters, state_manager).
- `Config.validate()` beim GUI-Start mit klaren Errors/Warnings.
- 4 Detector-Helper offiziell public umbenannt (kein _underscore).

### .exe-Build-Kit
- `app_launcher.py` (Stdlib-only Bootstrapper, findet .venv + gui.py),
  `bezys.spec` (PyInstaller, one-file), `build_exe.bat` (1-Klick-Build),
  `BUILD_EXE.md`. **NICHT** die Heavy-ML-Stack einbacken — Launcher startet
  gui.py in der .venv, exakt wie `start-gui.bat`. Build muss auf Windows
  laufen (PyInstaller cross-compilet nicht).

## Wie du (neue Claude-Instance) anfangen solltest

1. **Lies diese ganze CLAUDE.md.** Sie ist die einzige Wahrheit über
   Architektur + bisherige Entscheidungen.
2. `git log --oneline -30` für Recent Commits.
3. `pytest -q` muss durchlaufen (aktuell 185 grün).
4. **Sei ehrlich.** Der User schätzt klare "geht nicht weil X" mehr als
   optimistische Schätzungen. Wenn Code nicht testbar weil Sandbox-Limits
   — sag's, schick Mock-Tests + bitte um echten Test-Run vom User.
5. **Workflow-Konventionen aus Session 2:**
   - **Jeder Feature-Commit testet** mit echtem ffmpeg/Pillow wo möglich.
   - **GUI-Signature ↔ Inputs-List müssen 1:1 alignen** (Helper-Skript:
     params count + Reihenfolge per name). Mismatch = stiller Bug.
   - Pipeline-Funktionen die im GUI-Worker-Thread laufen → `on_step`
     IMMER durchreichen (sonst sieht User keine Fehler).
   - Bei größeren Features: **in saubere Batches commiten**, jeder
     getestet. Ein 5-Stunden-PR der zwölf Sachen ändert ist Risiko.
   - **Niemals** PowerShell-Beispiele dem User geben und JSON-Pfade mit
     einzelnen Backslashes — er hat sich daran schon mal verbrannt.
6. **Pipeline.py ist 5500+ Zeilen** und bleibt vorerst monolithisch. User
   hat das Splitting explizit verschoben (aktiv im Feature-Bauen). Nicht
   ohne explizite Aufforderung anfassen.
7. Wenn neue Effekte/Effekt-Regie: routen über `_complete_text` (honors
   Claude-CLI-Toggle), nicht direkt `_gemini_post`.

## Config.json — User hat (im echten config, NICHT example):
- output_dir, gemini_api_key, cloudflare_*, pixabay_api_key, pexels_api_key
- tts_reference_audio (Pfad zu seinem Voice-Sample für Cloning)
- tts_language: "en", tts_exaggeration 0.7, tts_cfg_weight 0.3 (Viral-Preset)
- youtube_cookies_from_browser: "edge"
- use_claude_cli: true (manchmal an, manchmal aus je nach Run)
- Branch: `claude/upgrade-roblox-autopilot-cdW3P`

## Recent commits (Session 2)

```
55501e8 photos: circuit-breaker — disable quota-exceeded source for the run
0fb5bae photos: add Pexels as the top-quality source (same key as videos)
b29afd2 batches B+C+D: per-word karaoke captions + multi-hook button + frame-thumbnails
93e7f4c batch A: stock B-roll VIDEOS in the middle slot via Pexels (free)
eefc166 effects batch 2: punch, ken-burns, slide-in, keyword-pop
e1bc3ee effects engine batch 1: KI-directed color-grade / flash / shake
377b3e8 emoji: place above the caption when caption is at the bottom
b9c936a claude CLI: auto-probe common npm-global locations when PATH lacks it
3374d75 claude CLI: fix Windows execution + make provider choice visible
1884d39 color caption emojis in landscape/long-form (were falling back to white)
c3e64d2 download: surface the real yt-dlp failure + actionable cookie hint
d715827 fix: apply theme/css at launch() (Gradio 6) + yt-dlp cookies
ec7cde1 exe: make it a venv-bootstrapper launcher (was crashing on startup)
b6a4605 gui: modern themed design + .exe build kit; refactor entry to main()
2302ee0 images: 0.5s gameplay gap between continuous images (start on-beat)
fa4c9c7 voice cloning: auto-prep any recording into a clean Chatterbox reference
8b10ea2 fix: SFX synced to image changes + tighter caption→emoji gap
bf3e92d images: per-beat changing visuals + free-photo source mix
```

## Recent commits (Session 1, älter)

```
9a60c7a multi-clip: forced distribution via per-region Gemini calls
a921d5f multi-clip robustness: distribution prompt, length floor, crash isolation
b70cd4d multi-clip: no length cap + source-audio captions when voice disabled
c6c7e76 multi-clip: Opus-style free length (Gemini decides duration per moment)
0af6ff6 multi-clip: per-clip target_duration matches snap-adjusted range
4ac50a9 multi-clip: gap-weighted snap, no print duplication, reframe-off warning
fb4d461 YOLOv11-face as primary detector
2c4f5e8 InsightFace primary face detector
3d28900 MediaPipe face detector
a29b41b whisper full-video transcription via subprocess
```

---

# Session 3 (Juni 2026 — selbe Branch `claude/upgrade-roblox-autopilot-cdW3P`) — Handoff für neuen Chat

Owner: **bezyzuta**, Kanal heißt **BloxGrave** (englische Roblox-Horror-Stories), macht
auch deutsche/englische Roblox-Shorts. Arbeitet auf Windows, RTX 3080, venv unter
`C:\Users\bezy\Desktop\roblox-shorts\bezyzuta`. **Tests:** `pytest -q` → aktuell ~300+
grün, EIN bekannter Fail (`test_prepares_clean_mono_capped_sample`) NUR weil im
Cloud-Container kein `ffmpeg` ist — auf der echten Maschine grün. Ignorieren.

## Arbeitsweise mit diesem User (WICHTIG)
- **Deutsch, ehrlich, keine Schmeichelei, konkrete Lösungen.** Er schätzt klares „geht
  nicht weil X" mehr als Optimismus. Wird manchmal grob/flucht wenn frustriert — nicht
  drauf eingehen, einfach sauber liefern.
- **Workflow pro Änderung:** Ursache im Code finden → fixen → Tests dazu → volle Suite →
  committen (klare Message, endet mit der Session-URL) → **pushen** zu
  `claude/upgrade-roblox-autopilot-cdW3P` → kurz erklären was er tun muss (`git pull` +
  evtl. config/GUI). Er rendert auf SEINER Maschine; ich (Cloud) kann nicht rendern
  (kein ffmpeg/GPU/Modelle).
- **HARTER INVARIANT — GUI param↔input alignment:** `gui.py` `generate(...)`-Signatur und
  die `inputs=[...]`-Liste am `generate_btn.click(` MÜSSEN 1:1 in Reihenfolge & Anzahl
  passen. Bei JEDER neuen GUI-Komponente prüfen mit diesem Snippet (zählt + vergleicht):
  ```python
  import ast, re; src=open('gui.py').read()
  fn=next(n for n in ast.walk(ast.parse(src)) if isinstance(n,ast.FunctionDef) and n.name=='generate')
  params=[a.arg for a in fn.args.args]
  m=re.search(r'(?<!hook_)generate_btn\.click\(',src); i2=src.index('inputs=[',m.start())
  d=0;j=i2+7;st=j
  while True:
      c=src[j]
      if c=='[':d+=1
      elif c==']':
          d-=1
          if d==0:break
      j+=1
  names=[t.strip() for t in re.sub(r'#.*','',src[st+1:j]).split(',') if t.strip()]
  print(len(params),len(names),params==names)
  ```
  Aktuell **81 = 81**. Lieber config-only (kein GUI-Param) wenn möglich → null Risiko.
- **`pipeline.py` (~6800 Zeilen) bleibt bewusst monolithisch.** Nicht splitten.
- Pipeline-Funktionen die im GUI/Bot-Worker laufen → `on_step` durchreichen.

## Was in Session 3 dazukam (alles auf der Branch, gepusht)

### LLM-Bild-Provider-Kaskade (AI-Bilder)
Reihenfolge im Bild-Beat: **Higgsfield → Grok → Cloudflare Flux → Pollinations** (Foto-
/Video-Beats davor: Pexels). Alle config-gated, automatischer Fallback bei Fehler.
- **Grok Build CLI** (`use_grok_cli`): `grok -p "<prompt>"` (Prompt ist ARGUMENT, nicht
  stdin!), Bild landet im Session-Ordner → Snapshot-Diff von `~/.grok` findet die neue
  Datei. `fetch_image_from_grok_cli`.
- **Higgsfield CLI** (`use_higgsfield_images`, Modell `higgsfield_image_model` default
  `nano_banana_2`): `higgsfield generate create <model> --prompt "..." --wait --json` →
  `result_url` aus JSON-Array → runterladen. `fetch_image_from_higgsfield`. Es gibt AUCH
  `fetch_video_from_higgsfield` (`use_higgsfield`/`higgsfield_video_model`) für Video-
  Beats, aber Video-Modellname kennt der User nicht → standardmäßig aus. User will
  Higgsfield für die BILDER (Strichmännchen), nicht Video.

### Bild-Stil-System (`image_style` cfg + GUI-Dropdown „🎨 Bild-Stil")
`_IMAGE_STYLE_PRESETS` + `_style_directive` + `_quality_suffix_for`. Werte:
`auto` (KI wählt pro Beat Medium), `roblox`, `realistic`, `cinematic`,
`ms_paint_stickman`, `doodle_sketch` (die 2 sind FLAT → nutzen `_IMAGE_STYLE_SUFFIX_FLAT`
statt des cinematischen Suffixes, sonst zerstört „rim lighting/saturated" den flachen
Look). `_roblox_cap`/`_enforce_roblox_cap`: in `auto` max `image_roblox_max` (default 2)
Roblox-Renders pro Video, Rest wird via `_derobloxify` zu realen Motiven umgeschrieben.
Forcierte Styles (inkl. flat) → 0 Roblox.

### Faceless Story Format (Danny-Why-Stil, Strichmännchen)
Output-Format-Radio hat 3. Option „📝 Faceless Story — 16:9 Querformat". Setzt
`job["faceless_mode"]=True`. Pipeline: **KEIN YouTube-Download** (kein Gameplay), baut
`make_color_background` (weiß) als Hintergrund; ALLE Bilder = AI im flat style (photos/
videos forced off); Bilder werden 16:9 generiert (`_save_aspect_image`/`_faceless_recrop`)
und FÜLLEN den Frame via `_fullframe_chain` (kein weißer Border, kein Tilt — sonst weiße
Ränder). `allow_continuous` lockert die portrait-Kopplung der durchgehenden Bilder.
Zeitstempel-Bild-Export (`export_timestamp_images` → `<slug>_timestamp_images/00_07.png`)
zusätzlich zum Video, opt-in. **Wichtig:** Faceless braucht KEINE URL.

### Horror-Effekte (KI-getimt, in `effects_enabled` CheckboxGroup)
Neben flash/shake/punch/color_grade/ken_burns/slide_in/keyword_pop/word_karaoke jetzt:
`red_flash`, `dark_pulse`, `glitch` (rgbashift), `creep` (langsamer Zoom), `horror_grade`
(global, kalt/entsättigt, `colorbalance` — NUR gültige Optionen rs/gs/bs/rm/gm/bm/rh/gh/bh,
NICHT „ms"!). `_EFFECT_PLAN_PROMPT` + `generate_effect_plan` platzieren sie. Bei langen
Videos bis ~20 Effekte.

### Skript-Länge wirklich treffen (war: 600s angefragt → 340s raus)
Zwei Ursachen gefixt: (1) Top-up forderte ganzen Deficit in 1 Call → LLM liefert nur
~halb. Jetzt `_continuation_block` (gebündelte ~280-Wort-Häppchen, Loop) +
`_extend_script_to_target`. (2) wps-Schätzung (2.5) ≠ echte TTS-Rate (~4.5 bei Viral-
Preset). Lösung: `_grow_voiceover_to_target` MISST nach dem TTS die echte Audio-Dauer,
rechnet reale wps, verlängert Skript + synthetisiert nur den Zusatz + concatet Audio
(`_concat_audio`), bis ~92% des Ziels. Greift nur bei `extend_script` + target>=90s.

### TTS-Sanitizing + Zahlen + Stimmen
- `_sanitize_script_for_tts` (läuft in `synthesize_voiceover` für ALLE): strippt
  Timestamps/Markdown/Regie-Anweisungen. KONSERVATIV: echte Zeiten („John 3:16",
  „5:30") bleiben, nur Klammer-/Dash-Timestamps + keyword-Regie raus.
- `_spell_numbers_for_tts`: Ziffern → Wörter pro Sprache (DE Jahr „1979" →
  „neunzehnhundertneunundsiebzig", `_de_number`/`_de_year`/`_en_*`). Sonst las TTS
  Zahlen als Müll vor.
- **Voice tempo** (`job["voice_tempo"]`, GUI-Slider 0.7-1.2): `apply_voice_tempo` (atempo,
  tonhöhen-erhaltend), VOR der Längenmessung. Für lange/Horror-Videos langsamer (0.85-0.9).
- **Deutsche Stimme klonen** (`tts_de_clone` + GUI-Checkbox „🇩🇪"): nutzt **Chatterbox
  Multilingual** (`_get_chatterbox_multilingual_model`, `language_id="de"`) statt Piper.
  Referenz: `tts_reference_audio_de` else `tts_reference_audio`. `_resolve_clone_reference`
  ist tolerant (findet `.clone.wav` ↔ Rohdatei-Geschwister). Fällt auf Piper zurück wenn
  Modell/Referenz fehlt. EN bleibt normales Chatterbox. Erster Lauf lädt ~3GB Multilingual-
  Modell. `chatterbox-tts` evtl. `pip install -U` falls Import `chatterbox.mtl_tts` fehlt.
- Englisch-Stimme: weiterhin Chatterbox + Voice-Cloning (Besmir-Stimme).

### Stabilität / Performance
- `_unload_tts_model()`: entlädt Chatterbox aus VRAM VOR der Bildphase — aber NUR bei
  vielen Bildern (>=12 geschätzt) oder `image_cooldown_secs`>0. Kleine Shorts behalten
  Modell → Batch lädt nicht jedes Mal neu. (User hatte PC-Absturz bei 50 Bildern =
  Hardware-Schutz/Netzteil; `image_cooldown_secs` Config gibt GPU Atempausen.)
- **Download schneller**: `download_gameplay` hat `--concurrent-fragments 5` +
  `--no-playlist` + `download_max_height` (config, default 1080; 720 = viel schneller bei
  Shorts, sieht im vertikalen Crop identisch aus). User nahm 44-Min-Quellen → langsam.
- Bild-Größe-Slider bis 50 Bilder, Bild-Dauer bis 5s, Bild-Größe default 1.0.
- Subscribe-Banner default „SUBSCRIBE" (war „ABONNIEREN").
- B-Roll-Videos (Pexels) werden quadratisch gecroppt wie die Foto-Cards (`_video_chain`).

### scene-plan Gemini-Retry (war: „nur 1/3 usable from Claude" obwohl Claude ok)
`generate_scene_plan` bewertet Plan-Qualität; bei <60% brauchbaren Beats Retry mit Gemini.
ABER: wenn Fotos/Videos AUS sind, bot der Prompt trotzdem „photo" an → Claude wählt photo
→ wird zu leerem AI-Beat → Retry. Gefixt: `photo_hint`/`mix_rule` im `_SCENE_PLAN_PROMPT`
sagen jetzt „nur source=ai mit echtem Motiv" wenn photos+videos off. KEIN Claude-Problem.

## Session 4 (Juni 2026 — Branch `claude/happy-fermat-Oy6Cg`)

### automation/ (eigenständig, rührt pipeline.py nicht an)
PC-Steuerung auf USER-Maschine (Cloud kann's nicht ausführen): `browser.py`
(Playwright, persistentes Login-Profil, DOM-robust), `chrome_attach.py` (CDP an
laufendes Chrome andocken → echte Tabs/Logins), `desktop.py` (pyautogui,
`click_image`), `recorder.py` (pynput record/replay), `snip_test.py`
(Win+Shift+S → Clipboard → PNG). Install via `automation/requirements-automation.txt`
+ `playwright install chromium`. `pytest.ini` `testpaths=tests` damit pytest die
automation-Skripte nicht sammelt (snip_test.py matcht `*_test.py`).

### yt-dlp Cookie-Hinweis
`_ytdlp_error_hint` erkennt jetzt „Could not copy ... cookie database" (#7271:
Browser läuft = DB gesperrt, oder Chrome v127+ App-Bound Encryption) → sagt
Browser schließen / cookies.txt exportieren / Browser wechseln. Lösung beim User:
`youtube_cookies_file` (cookies.txt) ODER cookies ganz aus für öffentliche Videos.

### WhisperX — wort-genaue Captions (opt-in, `use_whisperx` in config.json)
`transcribe_words_best()` Dispatcher: bei `cfg.use_whisperx` →
`transcribe_words_whisperx_subprocess`, sonst altes `transcribe_words_subprocess`.
**WICHTIG (User-Feedback "Text leicht schlechter"):** Erkennung läuft NICHT über
whisperx' batched pipeline (erkennt Wörter schlechter), sondern über SEQUENZIELLES
faster-whisper (gleiche Engine/Settings wie der alte Pfad → identischer Text).
WhisperX macht NUR das wav2vec2-Force-Align fürs Timing auf diesem Text. Align
schlägt fehl → faster-whispers eigene Word-Timestamps (= alter Pfad). Damit nie
schlechterer Text als vorher.
WhisperX-Fehler/fehlende Lib → automatischer Fallback, Render bricht NIE.
Gleiche Rückgabe `[(start,end,wort)]`. `_fill_word_gaps` füllt nicht-alignte
Tokens (Zahlen/Symbole) aus Nachbar-Timings statt sie zu droppen. Sprache aus
`job["tts_language"]` (Voice-Pfad) bzw. "auto" (Source-Audio-Captions). Gratis,
lokal, GPU. Beide run_one-Call-Sites umgestellt.

**WICHTIG — Dep-Konflikt:** `pip install whisperx` (3.8.x) zieht torch~2.8 /
numpy 2 / transformers 4.x rein und KILLT Chatterbox im Haupt-venv (braucht
torch cu124 / numpy<2 / transformers==5.2.0). Deshalb läuft WhisperX in einem
SEPARATEN venv: `cfg.whisperx_python` = Pfad zu dessen python.exe; der Subprocess
nutzt `python_exe=` statt `sys.executable`. Haupt-venv bleibt sauber. Fehlt der
Pfad/Interpreter → RuntimeError → Fallback. Setup-venv: `python -m venv
whisperx-venv`, darin `pip install torch torchaudio --index-url
https://download.pytorch.org/whl/cu128` + `pip install whisperx nvidia-cudnn-cu12
nvidia-cublas-cu12`. Reparatur Haupt-venv falls verseucht: `pip install "numpy<2"
"transformers==5.2.0"` + torch cu124 reinstall. config-only (kein GUI-Param).

### Caption-Polish (opt-in, Effekt `caption_polish` in „✨ Engagement-Effekte")
Neue CheckboxGroup-Option (KEIN neues GUI-Element → param↔input bleibt 81=81).
In `write_ass` neuer Branch + Param `caption_polish`: die 3-Wort-Gruppe bleibt
lesbar stehen, aber das gerade gesprochene Wort leuchtet (gelb `&H00FFFF&` +
`\fscx116\b1`) und wandert wortweise mit — nutzt das enge WhisperX-Timing.
Fade nur beim ersten/letzten Wort des Chunks (kein Flackern). Short-form only
(long_form ignoriert), Vorrang vor `word_karaoke`. Verdrahtet an der einzigen
write_ass-Call-Site aus `job["effects_enabled"]`. Tests: test_caption_polish.py.

### Auto-Hook (opt-in, GUI-Checkbox „🎣 Auto-Hook" im Hook-Accordion)
`generate_auto_hook(script, cfg, language)`: LLM schreibt EINEN Hook aus dem
ECHTEN Skript (nicht nur Topic), routet über `_complete_text` (Claude-CLI-aware),
Fallback → `generate_hook_variants[0]` → "". `_clean_hook_line` zieht eine saubere
Zeile (Quotes/Fence/Punkt weg, ≤60 Z.). In `run_one` vor `write_ass`: nur wenn
`job["auto_hook"]` UND Hook-Feld leer (manueller Hook gewinnt). NEUE GUI-Checkbox
→ Signatur+inputs+job-dict gezogen, param↔input jetzt **82=82**. Tests:
test_auto_hook.py.

### Dead-Air-Trim / Pacing (opt-in, GUI-Checkbox „✂️ Dead-Air-Trim")
`trim_internal_silence(in,out,threshold_db=-35,min_silence=0.4,keep_silence=0.2)`:
ffmpeg `silenceremove=stop_periods=-1` kürzt lange Pausen ÜBERALL, lässt
`keep_silence` Atempause. **Safety:** Output leer oder <50% vom Input → Original
behalten (threshold zu aggressiv). In `run_one` NACH voice_tempo, VOR der
vo_dur-Messung + Transkription → Captions/Bilder/SFX bleiben synchron (alles wird
danach aus dem getrimmten vo abgeleitet). `job["trim_silence"]` + optionale
config-tunes `trim_silence_threshold_db/min/keep`. NEUE GUI-Checkbox → param↔input
jetzt **83=83**. Tests: test_dead_air.py.

## config.json — User-relevante Felder (Session-3-Neuzugänge)
```
image_style ("auto"/.../"ms_paint_stickman"/"doodle_sketch"), image_roblox_max (2),
image_cooldown_secs (0), download_max_height (1080),
use_grok_cli, grok_cli_path, grok_cli_extra_args,
use_higgsfield_images, higgsfield_image_model ("nano_banana_2"), higgsfield_cli_path,
use_higgsfield, higgsfield_video_model (leer=aus),
tts_de_clone (false), tts_reference_audio_de,
telegram_* (Bot — IGNORIEREN, User nutzt stattdessen Claude Code remote)
```
Echte config.json des Users hat: output_dir `C:\Users\bezy\Desktop\Youtube`,
gemini_api_key, cloudflare_*, pexels_api_key, pixabay_api_key, tts_reference_audio (Besmir,
EN), tts_language wechselt er, use_claude_cli oft an (opus), whisper_model sollte er auf
`medium` setzen für bessere DE-Untertitel.

## Bekannte offene Punkte / TODO
- **Chatterbox Multilingual DE-Qualität** unbestätigt (ich kann kein Audio testen). User
  meldete: Stimme „fast perfekt", aber gelegentliche Aussprache-Verhaspler („glauben"→
  „blauben") = Modell-Artefakt, nicht code-fixbar; cfg_weight runter (~0.3) probieren.
- **Untertitel-Genauigkeit DE**: Whisper-Modell auf `medium`/`large-v3` für Deutsch.
- **Higgsfield Video-Modellname** fehlt noch (User müsste `higgsfield generate list` nach
  einem manuellen Video-Job ausführen). Bilder via nano_banana_2 laufen.
- **Telegram-Bot (`bot.py`)** existiert + getestet, aber User will ihn NICHT nutzen
  (macht Remote via Claude Code). Nicht weiter ausbauen außer er fragt.
- Multi-Clip-Qualität bleibt schwächer als Opus.pro (Modell-Limit), mit Claude-CLI besser.

## Wie neuer Chat anfangen sollte
1. Diese ganze CLAUDE.md lesen (v.a. diese Session-3-Sektion).
2. `git log --oneline -15`, `pytest -q` (der eine ffmpeg-Fail ist ok).
3. Ehrlich bleiben, in sauberen Batches arbeiten, param↔input-Check bei GUI-Änderungen,
   nach jedem Feature pushen + dem User sagen was er tun muss.
