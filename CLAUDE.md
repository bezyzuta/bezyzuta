# Bezys Shorts Generator — Project State

YouTube-Shorts-Generator-Pipeline (Roblox / Podcast / langform → kurze vertikale Shorts).
Owner: Besmir / bezyzuta. Aktuell lokales Tool, Roadmap: Web-App + Mobile-App.

## Repo

- **Branch:** `claude/youtube-shorts-roblox-setup-d13bP`
- **Working dir on user's machine:** `C:\Users\bezy\Desktop\roblox-shorts\bezyzuta`
- **Python:** 3.12, Windows venv at `.venv`
- **Entry points:** `gui.py` (Gradio web UI), `pipeline.py` (engine), `start-gui.bat`

## Features (Stand: aktuell aktiv)

### Video-Quelle
- Direkt-URL (yt-dlp) ODER Channel-Scrape mit Title-Filter
- Source-File-Cache für Multi-Clip

### Skript & Stimme
- ElevenLabs TTS (multilingual / flash / turbo Modelle)
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
- Sound-Effects pro Bild-Pop-In + pro Scene-Cut
- Subscribe-Sting (Sound bei Subscribe-Banner)
- Hook-Overlay (großer Text oben am Anfang, manuell)
- Pop-Captions (TikTok-Style Karaoke)
- Progress-Bar unten via color+scale+overlay
- Subscribe-Button am Ende
- Image-Overlays (Cloudflare Flux + Pollinations Fallback)

### Whisper
- faster-whisper auf CUDA (RTX 3080) mit subprocess-Isolation für lange Runs
- nvidia-cublas/cudnn/cuda-runtime wheels für Windows installiert

## Configs

`config.json` (NICHT `config.example.json`!):
- elevenlabs_api_key (neuer Account, hat noch Credits)
- gemini_api_key (frischer Free-Tier Account, 1500 RPD)
- cloudflare_account_id + cloudflare_api_token
- output_dir: `C:\Users\bezy\Desktop\Youtube`
- whisper_model: meist "base" oder "small"

## APIs / Services

| Wofür | Wer | Status |
|---|---|---|
| Skript-Generierung | Gemini 2.5 Flash | aktiv |
| Bild-Prompts | Gemini → Cloudflare Llama 3.1 | aktiv |
| TTS Voiceover | ElevenLabs | aktiv |
| Vision (Scene-Picking) | Gemini Vision → Cloudflare Llama 3.2 11B Vision | aktiv |
| Face Detection | YOLOv11-face (lokal) → MediaPipe | aktiv |
| Image Generation | Cloudflare Flux Schnell | aktiv |
| Transcription | Whisper (faster-whisper) lokal | aktiv |

## Lokale Pakete

In `.venv` installiert:
- `mediapipe`, `ultralytics`, `torch+cu124`, `torchvision`, `torchaudio`
- `nvidia-cublas-cu12`, `nvidia-cudnn-cu12<10`, `nvidia-cuda-runtime-cu12`, `nvidia-cuda-nvrtc-cu12`
- `faster-whisper`, `requests`, `yt-dlp`, `gradio`
- Coqui-TTS / Ollama wurden früher installiert, dann wieder entfernt — User bleibt bei ElevenLabs + Gemini

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
