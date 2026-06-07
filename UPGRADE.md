# Upgrade-Anleitung: Resume, YouTube Optimizer, Auto-Reframe v2

## TL;DR

Drei neue Features in der Pipeline (Branch `claude/upgrade-roblox-autopilot-cdW3P`):
**Resume + Logging**, **YouTube Optimizer** und **Auto-Reframe v2**. Alle sind
opt-in über GUI-Toggles bzw. Job-Dict-Flags. Wer nichts anhakt, bekommt exakt
das alte Verhalten — keine Migration nötig, kein Re-Render bestehender Jobs.

---

## Migration von Pre-Upgrade-Workflow

Nichts zu tun. Konkret:

- Bestehende `jobs.json` / `jobs.example.json` laufen unverändert weiter — die
  neuen Felder sind alle `False` / Default, wenn nicht gesetzt.
- `config.json` ändert sich nicht. Keine neuen API-Keys nötig (Resume nutzt
  nur das Dateisystem, YouTube-Optimizer nutzt die existierenden Gemini- und
  Cloudflare-Credentials, Reframe v2 die existierenden Detector-Modelle).
- Alte Slugs / Output-Verzeichnisse bleiben kompatibel. Resume schreibt nur
  zusätzlich `job_state.json` rein — der Rest der Output-Files ist identisch.
- Wer beim ersten Mal mit Resume an läuft, dann das Feature wieder ausschaltet:
  `job_state.json` bleibt liegen, stört aber nicht. Kann manuell gelöscht werden.

---

## Feature 1: Resume + Logging

### Wann sich's lohnt

- **Lange Multi-Clip-Jobs** (60-min-Video → 8 Sub-Clips à 90s). Wenn Sub-Clip
  6 von 8 crashed, will man nicht Whisper-Transkription + Download nochmal
  rennen lassen.
- **Langsame Whisper-Modelle** (`medium` / `large-v3` auf der RTX 3080,
  10-20 min auf langen Videos). Crash beim Compose-Step = ärgerlich ohne Resume.
- **Instabiles WLAN** beim yt-dlp-Download. Resume springt direkt zum nächsten
  Step wenn das mp4 schon vollständig auf der Platte liegt.
- **Iteration an Hook-Text / Captions**: Hat man Resume an + ändert nur den
  Hook-Text, läuft der Compose-Step neu — Voiceover/Bilder werden wiederverwendet.

### Wie anschalten

GUI → Accordion **🔄 Resume & Logging** → Checkbox **♻️ Resume aktiv**.
Im Job-Dict entspricht das `"resume": true`.

### Wo der State liegt

- Single-Clip: `{output_dir}/{slug}/job_state.json`
- Multi-Clip: `{output_dir}/{base_slug}__multiclip_work/job_state.json`,
  und für jeden Sub-Clip zusätzlich dessen eigene `job_state.json` im
  Sub-Clip-Verzeichnis.

Inhalt: Step-Liste mit `completed_steps`, Artefakt-Pfaden, Spec-Hash und
Timestamps. Plain-JSON, mit dem Texteditor lesbar.

### Wie man Resume „vergisst" und komplett neu rendert

`job_state.json` löschen. Das ist die ganze Schnittstelle.

```cmd
del C:\Users\bezy\Desktop\Youtube\<slug>\job_state.json
```

Bei Multi-Clip zusätzlich die `job_state.json` im
`__multiclip_work`-Verzeichnis löschen, falls auch der Moment-Pick neu laufen soll.

### Log-Levels

Dropdown im selben Accordion. Wirkt sich nur auf die formatierten Log-Zeilen
aus (`[12:43:01 WARN ] …`), nicht auf die Roh-`step()`-Ausgaben der Pipeline.

| Level | Wann benutzen |
|---|---|
| `DEBUG` | Detector-Kaskade debuggen (welcher Detector hat was gesehen, pro Segment). Wenn Reframe komisch cropt. |
| `INFO`  | Standard. Pipeline-Fortschritt + relevante Warnungen. |
| `WARN`  | Lange Runs, GUI soll ruhig bleiben. Nur wirkliche Probleme. |
| `ERROR` | Praktisch nie. Würde auch Step-Fortschritt verstecken. |

### Gotcha: Spec-Hash-Warnung

Über alle relevanten Job-Felder (Topic, Skript, Reframe-Modus, etc.) wird ein
SHA-256 berechnet und im State abgelegt. Wenn der Hash beim zweiten Lauf
abweicht, kommt im Log:

```
[WARN ] resume: job parameters changed since last run
        (hash abc123 → def456); completed steps will still be reused —
        delete job_state.json to force a full re-render
```

Bedeutung: Du hast zwischen den Läufen Parameter editiert. Die bereits
fertigen Schritte werden **trotzdem wiederverwendet** — das ist Absicht
(sonst wäre die Warnung schon der Re-Render). Wenn du wirklich alles neu
willst: `job_state.json` löschen.

Die genauen Felder, die in den Hash einfließen, stehen in
`state_manager.py` unter `_SPEC_KEYS_FOR_HASH`. Dinge wie `batch_count` sind
bewusst ausgeschlossen.

### Was Resume automatisch handled

- **Artefakt-Datei gelöscht** (z.B. Voiceover-mp3 manuell weggeworfen): Step
  wird als nicht-fertig markiert und neu gerannt, auch wenn er im State steht.
  Siehe `StateStore.is_done()` in `state_manager.py`.
- **Crash mitten im Schreiben** der `job_state.json`: atomare Writes via
  temp-file + rename, also keine halben JSONs auf der Platte.
- **Sub-Clip-Granularität in Multi-Clip**: Jeder Sub-Clip hat seinen eigenen
  `run_one`-State. Crash in Sub-Clip 7 → beim Resume läuft Sub-Clip 7
  da weiter, wo er war (z.B. Compose-Step), nicht von vorne.

---

## Feature 2: YouTube Optimizer

### Wann sich's lohnt

Jeder Short, den du tatsächlich hochladen willst. Spart ~2 Minuten pro Upload
(Titel ausdenken, Tags zusammenklicken, Thumbnail-Prompt schreiben). Keine
zusätzlichen Kosten — nutzt deine bestehenden Gemini-Free-Tier-Credits.

Lohnt sich **nicht**, wenn du eh schon einen festen Title-Pattern hast und
manuell uploaden willst.

### Wie anschalten

GUI → Accordion **📈 YouTube Optimizer** → Checkbox **📝 YouTube-Metadaten generieren**.

Sub-Optionen:
- **🖼️ Thumbnail-Bild dazu generieren** (Cloudflare Flux / Pollinations Fallback).
  Default an. Erzeugt `{slug}_thumb.png`.
- **Sprache für Metadaten**: `auto` / `de` / `en`. `auto` übernimmt die Skript-Sprache.

### Output-Files

Neben dem fertigen `{slug}.mp4`:

| Datei | Zweck |
|---|---|
| `{slug}.youtube.json` | Maschinen-lesbar. Felder: `title`, `description`, `tags`, `thumbnail_prompt`, optional `thumbnail_path`. |
| `{slug}.youtube.txt`  | Copy-Paste-Format mit Sections `=== TITLE ===`, `=== DESCRIPTION ===`, `=== TAGS ===`, `=== THUMBNAIL PROMPT ===`. |
| `{slug}_thumb.png`    | Nur wenn Thumbnail-Checkbox an. |

### Workflow: Copy-Paste in YouTube Studio

1. YouTube Studio → Hochladen → `{slug}.mp4` wählen.
2. `{slug}.youtube.txt` im Editor öffnen.
3. Title-Block → Titel-Feld. Description-Block → Beschreibungsfeld. Tags-Block
   → Tags-Feld (Komma-getrennt, YouTube parsed das).
4. Thumbnail-Tab → `{slug}_thumb.png` hochladen, falls generiert.
5. `=== THUMBNAIL PROMPT ===` ist nur Referenz, falls man das Bild in
   Photoshop nachbauen / verbessern will.

### Provider-Fallback erklärt

Reihenfolge (in `youtube_optimizer.generate_youtube_metadata`):

1. **Gemini 2.5 Flash** über den existierenden API-Key. Schnell, hohe
   Free-Tier-Quota (1500 RPD), gibt brauchbares JSON.
2. **Cloudflare Llama 3.1 8B** wenn Gemini fehlschlägt (API down,
   Quota leer, Auth-Error).
3. **Template-Fallback** wenn beide weg sind: baut Titel aus Topic,
   Description aus den ersten Skript-Zeilen, Tags aus Topic-Keywords + Generic
   Roblox/Shorts-Pool. Posting-ready, aber natürlich nicht so gut wie LLM-Output.

**Wichtig**: Die Pipeline failt nie, weil Metadaten nicht generierbar waren.
Wenn der Template-Fallback greift, steht das im Log als WARN.

### Was tun wenn Titel / Description nicht gefällt?

Die Sidecar-Files (`.youtube.json` und `.youtube.txt`) sind plain Text. Einfach
editieren, kein Re-Run der Pipeline nötig. Das mp4 selber ist davon unberührt.

Wer das LLM nochmal befragen will: Toggle aus, Toggle wieder an, neu laufen lassen.
Mit Resume an überspringt die Pipeline alle teuren Steps und macht nur den
`youtube_metadata`-Step neu — das ist der ganze Trick.

### Direkt-Upload zur YouTube API (manuell)

Bewusst **nicht** aus der GUI verdrahtet. Grund: der User soll die Sidecars
prüfen und ggf. editieren, bevor ein Upload startet. Versehentliche
Auto-Uploads mit halluziniertem Clickbait-Titel = peinlich.

Wer trotzdem automatisieren will: `upload_to_youtube()` in
`youtube_optimizer.py` ist implementiert.

Setup:
```cmd
.venv\Scripts\python.exe -m pip install google-auth google-auth-oauthlib google-api-python-client
```

OAuth-Secrets-Datei holen:
1. https://console.cloud.google.com → APIs & Services → Credentials
2. OAuth client ID → Desktop application
3. JSON runterladen, z.B. nach `C:\Users\bezy\Desktop\roblox-shorts\yt_secrets.json`

Aufruf (in einem Python-Snippet, nicht in der GUI):
```python
from pathlib import Path
import json
from youtube_optimizer import YouTubeMetadata, upload_to_youtube

video = Path(r"C:\Users\bezy\Desktop\Youtube\my_slug.mp4")
meta_dict = json.loads((video.with_suffix("").with_name(video.stem + ".youtube.json")).read_text(encoding="utf-8"))
meta = YouTubeMetadata(
    title=meta_dict["title"],
    description=meta_dict["description"],
    tags=meta_dict["tags"],
    thumbnail_prompt=meta_dict["thumbnail_prompt"],
    thumbnail_path=meta_dict.get("thumbnail_path"),
)
url = upload_to_youtube(
    video, meta,
    oauth_secrets_file=r"C:\Users\bezy\Desktop\roblox-shorts\yt_secrets.json",
    privacy_status="private",   # erst auf private, später manuell auf public
)
print(url)
```

Beim ersten Aufruf öffnet sich ein Browser-Fenster für OAuth-Consent. Das
Token wird neben den Secrets gecached (`yt_secrets.token.json`), spätere
Calls laufen ohne Browser.

---

## Feature 3: Auto-Reframe v2

### Wann sich's lohnt

- **Podcast-Videos** (zwei Speaker nebeneinander). v1 hat das größte Face
  gesucht und an den Rand gejagt → einer der Speaker komplett aus dem Frame.
  v2 erkennt „mehrere Faces ähnlicher Größe = Podcast-Layout" und bleibt mittiger.
- **Speaker, der sich bewegt** (links-nach-rechts läuft im Studio). v1 hat
  über das ganze Clip gemittelt → mittig gecroppt mit beiden Rändern ab. v2
  macht per-Segment-Crops und folgt der Bewegung.
- **Alles, wo v1 zentral gecropt hat trotz angehaktem Reframe.** Häufig
  Motion-Blur oder Hard-Cut auf der Sample-Stelle → v1 gab `0.5` zurück, v2
  hat 3 Samples + Hold-Last.

### Wie anschalten

Im Accordion mit Reframe-Toggle:
1. **Auto-Reframe** (das alte Toggle) muss AUCH an sein. v2 ist nur ein
   Sub-Toggle, kein Ersatz.
2. **⚡ Auto-Reframe v2** anhaken.
3. Optional: Slider **Samples pro Segment (v2)** anpassen (Default 3).

Im Job-Dict: `"auto_reframe": true` UND `"reframe_v2": true`.

### Was anders ist als v1

| Aspekt | v1 | v2 |
|---|---|---|
| Single-Clip Sampling | 10 Samples + Median über das ganze Clip | Per-Segment-Timeline (auto ~3s Buckets) |
| Multi-Cut Sampling | Per-Segment, 1 Sample | Per-Segment, 3-5 Samples |
| No-Face-Fallback | `0.5` (zentriert) | Hold-Last: vorheriger Segment-Offset |
| Gewichtung | Größtes Face wins | Konfidenz-Gewichtung (Box-Größe) |
| Frame-Jitter | Adjacent Outlier kann mittendrin springen | Temporal Smoothing zum Vorgänger |
| Multi-Face | Größtes wird immer verfolgt | Podcast-Detection → zentrierter Crop |

Die Detector-Kaskade ist **gleich**: YOLOv11-face → InsightFace → MediaPipe.
v2 importiert die Adapter direkt aus `pipeline.py`, kein eigener Detector-Code.

### Samples-Slider

Range 1-7, Default 3.

- **1**: schnellster Pfad, im Prinzip v1-Verhalten pro Segment (kein
  Sample-Voting). Macht nur Sinn wenn die Pipeline jetzt schon zu langsam ist.
- **3**: Sweet Spot. Genug für Motion-Blur-Toleranz, schnell genug für
  Multi-Clip-Jobs.
- **5-7**: Wenn v2 immer noch zittert. Jeder zusätzliche Sample = ein
  ffmpeg-Frame-Extract pro Segment, das wird linear teurer.

### Wenn v2 KEINE Verbesserung bringt

Schritt 1: Log auf DEBUG stellen und nochmal laufen lassen. Suche im Log nach:
- `"yolo"` — YOLOv11 läuft, ideal. RTX 3080 = ~5ms/Frame.
- `"insightface"` — Fallback. Auch ok.
- `"mediapipe"` — Floor. Erkennt Faces nicht so robust, vor allem bei
  schrägen Blickwinkeln. Wenn fast alle Segmente `mediapipe` sagen, ist die
  YOLO-Pipeline nicht installiert oder kann die Weights nicht laden.

Schritt 2: Prüfen ob `ultralytics` und das YOLO-Weight-File da sind. Siehe
`pipeline.py` → `_get_yolo_face_detector()`.

Schritt 3: Wenn die Detector-Kaskade ok ist, aber v2 trotzdem schlecht cropt:
Das Material ist wirklich schwer (z.B. Roblox-Avatare ohne menschliche
Gesichter). Reframe komplett aus + manuell mit `clip_segments`/`manual_ranges`
arbeiten.

---

## Job-Dict-Referenz (für manuelle `jobs.json`)

| Feld | Typ | Default | Bedeutung |
|---|---|---|---|
| `resume` | `bool` | `false` | Checkpointing aktiv. State liegt in `{output_dir}/{slug}/job_state.json`. |
| `log_level` | `"DEBUG"\|"INFO"\|"WARN"\|"ERROR"` | `"INFO"` | Log-Level für die formatierten Log-Zeilen. |
| `reframe_v2` | `bool` | `false` | Aktiviert smoothed v2-Algorithmus. Nur wirksam wenn `auto_reframe=true`. |
| `reframe_samples_per_seg` | `int` (1-7) | `3` | Wie viele Frames pro Segment für die Face-Detection genommen werden. |
| `youtube_metadata` | `bool` | `false` | Generiert `.youtube.json` + `.youtube.txt` Sidecar zum fertigen mp4. |
| `youtube_thumbnail` | `bool` | `false` | Zusätzlich `{slug}_thumb.png` via Cloudflare Flux / Pollinations. |
| `youtube_lang` | `"auto"\|"de"\|"en"` | `"auto"` | Sprache für generierte Metadaten. `auto` = Skript-Sprache übernehmen. |

Minimal-Beispiel für eine `jobs.json`-Entry mit allen drei Features an:

```json
{
  "slug": "roblox_brookhaven_glitch",
  "topic": "Brookhaven RP glitch 2026",
  "source_url": "https://www.youtube.com/watch?v=...",
  "auto_reframe": true,
  "reframe_v2": true,
  "reframe_samples_per_seg": 3,
  "resume": true,
  "log_level": "INFO",
  "youtube_metadata": true,
  "youtube_thumbnail": true,
  "youtube_lang": "auto"
}
```

---

## Troubleshooting

### „Resume zeigt Step done, aber Datei fehlt"

Wird automatisch gehandled: `StateStore.is_done()` prüft bei jedem Step, ob
die im `artifacts`-Dict referenzierten Datei-Pfade noch existieren. Wenn
nicht, wird der Step aus `completed_steps` entfernt, der State neu gespeichert
und der Step re-rendert. Im Log:

```
[WARN ] resume: artifact missing for step 'voiceover'
        (voiceover_path=C:\…\vo.mp3); will re-run this step
```

Wenn das nicht passiert: in `job_state.json` schauen, ob der Artefakt-Key
mit `_path` oder `_file` endet — nur dann macht `is_done()` den Existenz-Check.
Andere Keys (z.B. `subject_offset`) gelten als Skalarwerte und werden nicht geprüft.

### „YouTube-Optimizer fällt immer auf Template"

Im Log auf `youtube_metadata`-Zeilen filtern. Erwartete Reihenfolge bei
funktionierendem Setup:

```
youtube_metadata: trying gemini ...
youtube_metadata: gemini ok (title=...)
```

Wenn stattdessen:
```
youtube_metadata: gemini failed (HTTP 429 / 401 / timeout)
youtube_metadata: trying cloudflare ...
youtube_metadata: cloudflare failed (...)
youtube_metadata: falling back to template
```

→ entweder Gemini-Quota leer (1500 RPD, refresht nach Mitternacht UTC) oder
API-Key falsch in `config.json`. Cloudflare-Fallback braucht
`cloudflare_account_id` + `cloudflare_api_token` in `config.json`.

Quick-Test ohne Pipeline:
```python
from youtube_optimizer import generate_youtube_metadata
import json
cfg = json.loads(open(r"config.json", encoding="utf-8").read())
meta = generate_youtube_metadata(topic="Test", script="Das ist ein Test-Skript.", cfg=cfg)
print(meta.to_dict())
```

### „Reframe v2 läuft deutlich langsamer als v1"

Erwartet. Pro Segment werden N Frames extrahiert statt 1, also ~N× so viele
ffmpeg-Subprozesse für den Detect-Step. Auf einer RTX 3080 mit YOLOv11 ist
der Detect selber billig (~5ms), aber der Frame-Extract via ffmpeg ist
overhead-dominiert.

Wenn zu langsam: Slider auf 2 oder 1 runter. Bei 1 ist v2 ungefähr v1-Speed
mit den anderen v2-Improvements (Multi-Face-Awareness, Hold-Last, Smoothing).

### „Multi-Clip Resume rendert komplett neu, obwohl Resume an war"

Wahrscheinlich falsches Verzeichnis. Multi-Clip schreibt seinen State **nicht**
ins normale `{output_dir}/{slug}/`, sondern in
`{output_dir}/{base_slug}__multiclip_work/job_state.json`. Wenn der `base_slug`
zwischen Läufen anders ist (z.B. weil `topic` minimal geändert wurde und der
Slug daraus abgeleitet wird), legt die Pipeline einen neuen Ordner an und
findet den alten State natürlich nicht.

Check:
```cmd
dir C:\Users\bezy\Desktop\Youtube\*__multiclip_work
```

Wenn dort zwei Ordner mit ähnlichen Namen sind → den richtigen reinkopieren oder
beim 2. Lauf den Slug fixieren (in der GUI das „Manueller Slug"-Feld setzen,
falls vorhanden, sonst im jobs.json-Workflow den `slug` explizit angeben).

### „Spec-Hash-Warnung obwohl ich nichts geändert habe"

Möglich wenn ein Default-Wert sich zwischen Pipeline-Versionen geändert hat
und im State noch der alte Hash steht. Lösung: einmal mit Resume aus laufen
lassen → neuer State wird geschrieben → Resume wieder an. Oder eben
`job_state.json` löschen.

---

## Related Files

- `state_manager.py` — Resume + Logger-Implementation. Single Source of Truth
  für Step-Namen ist die `Step`-Class.
- `youtube_optimizer.py` — Metadaten-Generator, Thumbnail-Wrapper, Upload-Stub.
- `reframe_v2.py` — Per-Segment-Face-Tracking mit Smoothing.
- `gui.py` — Accordions „🔄 Resume & Logging" (ab ~Zeile 571), „📈 YouTube
  Optimizer" (~Zeile 590), „⚡ Auto-Reframe v2" (~Zeile 374).
- `pipeline.py` — Integriert alle drei Features (Resume-Calls an den
  passenden Step-Stellen, Reframe v2 wird lazy importiert wenn Flag an).
- `CLAUDE.md` — Projekt-Status, vollständiger Feature-Überblick, Roadmap.
