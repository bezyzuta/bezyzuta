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
- **Durchgehende Mittel-Bilder** (`images_continuous`, `_image_schedule(continuous=True)`
  reiht Bilder lückenlos aneinander statt Pop-mit-Lücke — nur Hochformat)
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
  manchmal mittelmäßige Momente. User ist frustriert deswegen.
- **CLAUDE.md** ist dieser Datei (gerade von Claude geschrieben).
- Token-Verbrauch im Chat fast bei 1M — User wechselt zu frischem Chat.

## Wie du (neue Claude-Instance) anfangen solltest

1. Lies `pipeline.py` und `gui.py` — die Kernlogik
2. Lies `requirements.txt` — was an Deps schon da ist
3. Schau `git log --oneline -20` — wo wir zuletzt waren
4. Wenn User nochmal Multi-Clip testet und Quality wieder schlecht ist:
   - Custom Trained Model für Moment-Picking ist die einzige echte Lösung
   - Alternativ: Gemini 2.5 Pro statt Flash (besser, teurer)
   - Oder: User gibt manuelle Hinweise im Prompt was er sucht

## Recent commits (relevant)

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
