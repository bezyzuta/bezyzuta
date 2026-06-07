# Autopilot — Videos bauen + zu YouTube hochladen, OHNE Claude-Tokens

Der Autopilot rendert eine **Warteschlange** von Videos lokal und lädt sie
optional automatisch zu YouTube hoch. Er nutzt **dieselbe Pipeline wie die GUI**
(`run_one` / `run_multiclip`), aber **kein Claude** — die eigentliche Erstellung
läuft auf Gemini Free-Tier + lokalem TTS/ffmpeg. Tokens kostet nur das
*Bauen/Ändern* per Chat, nicht das tägliche Abspielen.

## Schnellstart (3 Schritte)

1. **Queue anlegen:** Kopiere `autopilot.example.json` → `autopilot.jobs.json`
   und trage deine Videos ein (siehe Felder unten). Pflicht ist nur `topic`.
2. **Doppelklick auf `start-autopilot.bat`.** Es arbeitet alle Jobs ab und
   schreibt den Status nach `autopilot_state.json`.
3. Fertig. Bereits erledigte Jobs werden beim nächsten Lauf übersprungen
   (erneut erzwingen: `start-autopilot.bat --force`).

> Ohne Upload brauchst du gar nichts weiter einzurichten. Der YouTube-Upload
> braucht ein **einmaliges Google-Setup** (siehe unten).

## Die Queue (`autopilot.jobs.json`)

```json
{
  "config": "config.json",
  "shutdown_when_done": false,
  "jobs": [ { "topic": "..." }, { "topic": "..." } ]
}
```

Pro Job-Eintrag:

| Feld | Bedeutung |
|---|---|
| `topic` | **Pflicht.** Thema/Prompt fürs Skript. |
| `output_format` | `portrait` (9:16, Default), `landscape` (16:9), `faceless` (Story 16:9, Strichmännchen), `ai_image_short` (9:16 KI-Bilder, keine YT-Quelle). |
| `source_url` | YouTube-URL als Gameplay-Quelle (für portrait/landscape). |
| `channel_url` + `title_filter` | Statt fester URL: Kanal scrapen + nach Stichwörtern filtern. |
| `script` | Eigenes Skript (überschreibt `topic`-Generierung). |
| `tts_language` | `de` / `en` / `auto`. |
| `image_style` | `auto`/`roblox`/`realistic`/`cinematic`/`ms_paint_stickman`/`doodle_sketch`. |
| `multiclip_enabled` + `multiclip_count` | Opus-Style: mehrere Clips aus einem langen Video. |
| `use_claude_cli` | `true` = Claude-CLI fürs Moment-Picking (kostet Abo-Limits, nicht Chat-Tokens). |
| `overrides` | Beliebige **Job-Felder** (z.B. `{ "target_duration": 90, "effects_ai": true }`). |
| `cfg_overrides` | Beliebige **config-Felder** (z.B. `{ "whisper_model": "medium" }`). |
| `upload` | `{ "enabled": true, "privacy": "private"\|"unlisted"\|"public", "playlist_id": "", "publish_at": "2026-06-10T08:00:00Z" }` |

`shutdown_when_done: true` fährt den PC nach **fehlerfreiem** Lauf in 60s runter
(abbrechen: `shutdown /a`).

## YouTube-Upload einrichten (einmalig, ~10 Min)

1. **Google Cloud Console** → neues Projekt (oder bestehendes).
2. **APIs & Services → Library →** „YouTube Data API v3" **aktivieren**.
3. **OAuth-Zustimmungsbildschirm** konfigurieren (User-Typ „Extern" reicht;
   füge deine eigene Google-Mail als **Testnutzer** hinzu — sonst blockt Google
   den Upload).
4. **Anmeldedaten → OAuth-Client-ID erstellen → Typ „Desktop-App".**
   JSON herunterladen und als **`client_secret.json`** in den Projektordner
   (dort wo `autopilot.py` liegt) legen.
5. Google-Libs in die venv installieren:
   ```
   .venv\Scripts\python.exe -m pip install google-api-python-client google-auth-oauthlib
   ```
6. **Einmal interaktiv autorisieren** (NICHT während du weg bist) — am
   einfachsten einen Job mit `upload.enabled = true` laufen lassen; beim ersten
   Upload öffnet sich der Browser, du loggst dich ein und erlaubst den Zugriff.
   Danach liegt `youtube_token.json` im Ordner und **alle weiteren Uploads
   laufen unbeaufsichtigt** (Token wird automatisch erneuert).

### Hinweise / Limits
- **Quota:** Ein Upload kostet ~1600 Einheiten, Standard-Kontingent 10.000/Tag
  → **~6 Uploads/Tag** kostenlos. Mehr brauchst du nicht selten zu beantragen.
- **Titel/Beschreibung/Tags** kommen automatisch aus dem
  `{video}.youtube.json`-Sidecar, das die Pipeline erzeugt (`youtube_metadata`
  wird bei aktiviertem Upload automatisch eingeschaltet).
- **`privacy: "private"`** ist die sichere Default-Wahl — du prüfst die Videos
  und stellst sie manuell auf öffentlich. `publish_at` plant die
  Veröffentlichung (Video bleibt bis dahin privat).
- **Kategorie** ist fix `20` (Gaming). Bei Bedarf pro Job:
  `upload.category_id`.
- Schlägt ein Upload fehl (Token abgelaufen, Quota leer, Libs fehlen), wird das
  **Video trotzdem gerendert** und der Fehler protokolliert — die Queue läuft
  weiter.

## Per Aufgabenplaner statt Doppelklick (optional)
Wenn du es zeitgesteuert willst:
```
schtasks /create /tn "BloxGrave Autopilot" /tr "\"C:\Users\bezy\Desktop\roblox-shorts\bezyzuta\start-autopilot.bat\"" /sc DAILY /st 08:00
```

## CLI-Flags
```
python autopilot.py [autopilot.jobs.json] [--force] [--no-upload] [--no-shutdown]
```
- `--force` — auch schon erledigte Jobs neu rendern.
- `--no-upload` — diesmal nur rendern, keine Uploads.
- `--no-shutdown` — `shutdown_when_done` ignorieren.
