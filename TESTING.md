# Manuelle QA-Test-Checkliste — Bezys Shorts Generator

**Branch:** `claude/upgrade-roblox-autopilot-cdW3P`
**Scope:** Drei neue opt-in Features (Resume + Logging, YouTube-Optimizer, Auto-Reframe v2).
**Grundregel:** Wenn ALLE neuen Flags aus sind, MUSS das Verhalten byte-identisch zur Pre-Merge-Pipeline sein.

> Format: `[ ] Test-Name` + Setup + Expected Result. "Risiko" markiert bekannte Stolperfallen.
> Tester-Hinweise (Vorbereitung) am Ende des Dokuments.

---

## 0. Vorbereitung (einmalig vor allen Tests)

- [ ] **0.1 Sauberes Output-Dir**
  - Setup: `config.json` → `output_dir` zeigt auf leeres Test-Verzeichnis (z.B. `C:\Users\bezy\Desktop\Youtube_TEST`).
  - Expected: GUI startet ohne Warnings, Verzeichnis ist leer.
- [ ] **0.2 API-Keys konfigurieren**
  - Setup: `config.json` enthält `elevenlabs_api_key`, `gemini_api_key`, `cloudflare_account_id`, `cloudflare_api_token`.
  - Expected: `gui.py` startet, "API-Status" im Header zeigt grüne Häkchen.
- [ ] **0.3 Test-Video bookmarken**
  - Setup: Drei feste YouTube-URLs notieren — (a) Single-Speaker 60s+, (b) Podcast 2-Personen-Layout, (c) Gameplay-Video ohne Gesichter.
  - Expected: Alle drei laden via yt-dlp ohne 403/429.

---

## 1. Regression-Tests (Default = OFF muss unverändert sein)

- [ ] **1.1 Single-Clip ohne neue Flags**
  - Setup: GUI starten, Video-URL (a) eingeben, alle drei neuen Toggles (`resume`, `reframe_v2`, `youtube_metadata`) bleiben AUS, Auto-Reframe AUS, alle anderen Felder Default.
  - Expected: Pipeline läuft, Output `{slug}.mp4` wird erzeugt. Kein `job_state.json` im Slug-Ordner, kein `.youtube.json`, kein `_thumb.png`. Log-Zeilen sehen aus wie vor dem Merge (keine `[12:34:56 INFO]`-Prefixe).
  - Risiko: Wenn `Logger` ohne Toggle plötzlich Prefixe schreibt, ist die Regression gebrochen.
- [ ] **1.2 Multi-Clip ohne neue Flags**
  - Setup: GUI, Video (b), Multi-Clip an, 3 Clips, neue Flags alle aus.
  - Expected: 3 Clips werden gerendert. Im `{base_slug}__multiclip_work/` liegt NUR `full_transcript.json` — KEIN `job_state.json`. Pro Clip-Ordner kein State-File.
- [ ] **1.3 Diff-Check Output**
  - Setup: Lauf 1.1 zweimal mit gleichem Seed-Video, Outputs vergleichen (ffprobe + Filehash erlaubt sind anders durchs Encoding; ASS-Captions sollten aber identisch sein).
  - Expected: Captions deterministisch, Bildanzahl konstant. (Random-Picks bei BGM können differieren — das ist erlaubt.)
- [ ] **1.4 Logger fällt auf print() zurück**
  - Setup: Job-Dict ohne `log_level` (über `pipeline.py --jobs ...` CLI starten, ohne GUI).
  - Expected: Pipeline läuft. Logger default-Level "INFO". Keine Exceptions, Output identisch.
- [ ] **1.5 Spec-Hash-Keys vollständig**
  - Setup: `_SPEC_KEYS_FOR_HASH` in `state_manager.py` Zeilen 139-147 visuell prüfen.
  - Expected: Alle output-beeinflussenden Job-Felder gelistet. Risiko: Fehlt z.B. `hook_text`, würde Spec-Hash nicht warnen wenn User das ändert.

---

## 2. Resume-Tests (`resume: true`)

### 2.1 Single-Clip Step-by-Step Resume

- [ ] **2.1.1 Abbruch nach Download**
  - Setup: Resume an, Video (a) starten. Wenn Log "[1/5] download" abgeschlossen ist und "[2/5]" beginnt → `Ctrl+C` im Terminal (bzw. GUI-Tab schließen). Direkt nochmal "Generieren" mit gleichem Slug.
  - Expected: Log zeigt `[1/5] resume: source already downloaded (...)`. Step 2 wird neu gemacht. `job_state.json` enthält `download` als done.
- [ ] **2.1.2 Abbruch nach Script**
  - Setup: Lauf abbrechen nach "skript fertig", erneuter Run.
  - Expected: Resume-Zeile `resume: script cached (N chars)`. Voiceover wird neu erzeugt.
- [ ] **2.1.3 Abbruch nach Voiceover**
  - Setup: Abbruch direkt nach ElevenLabs-Call. Re-Run.
  - Expected: `[2/5] resume: voice cached (voice.mp3, X.Xs)`. Scene-Pick startet.
- [ ] **2.1.4 Abbruch nach Scene-Pick**
  - Setup: Abbruch nach Clip-Cut. Re-Run.
  - Expected: `[3/5] resume: clip cached`. Transkription startet.
- [ ] **2.1.5 Abbruch nach Transcribe**
  - Setup: Abbruch nach Whisper. Re-Run.
  - Expected: `[4/5] resume: transcript cached (N words)`. Captions werden neu erzeugt (oder cached, je nach Reihenfolge).
- [ ] **2.1.6 Abbruch nach Captions**
  - Setup: Abbruch nach `captions.ass` ist geschrieben. Re-Run.
  - Expected: `resume: captions.ass cached`. Image-Step startet.
- [ ] **2.1.7 Abbruch nach Images**
  - Setup: Abbruch nach allen Bildern. Re-Run.
  - Expected: `resume: N image(s) cached`. Reframe startet (oder skipped wenn aus).
- [ ] **2.1.8 Abbruch nach Reframe**
  - Setup: Auto-Reframe an, Abbruch nach Reframe-Step. Re-Run.
  - Expected: `resume: reframe offset cached`. Compose startet.
- [ ] **2.1.9 Abbruch nach Compose**
  - Setup: Compose fertig, finales mp4 da, Abbruch vor Pipeline-Ende. Re-Run.
  - Expected: `resume: final video already rendered`. Pipeline endet sofort (oder YT-Meta wenn aktiv).

### 2.2 Artefakt-Invalidierung

- [ ] **2.2.1 Voice.mp3 manuell löschen**
  - Setup: Resume an, kompletter Run fertig. User löscht `{slug}/voice.mp3`. Re-Run.
  - Expected: Warn-Log `resume: artifact missing for step 'voiceover' (voice_path=...); will re-run this step`. Voiceover wird neu erzeugt, Rest aus Cache.
  - Risiko: `state_manager.is_done()` prüft nur Keys, die auf `_path`/`_file` enden — Artefakte mit anderen Keys werden NICHT validiert. Stichprobe: `script_text` ist Inhalt, nicht Path → wird nicht geprüft, OK.
- [ ] **2.2.2 Clip.mp4 löschen (Scene-Pick-Output)**
  - Setup: Wie 2.2.1 mit `clip.mp4` löschen.
  - Expected: Scene-Pick re-runs. Aber Achtung: Downstream-Caches (Captions, Images, Reframe, Compose) verwenden alte `transcript`, `ass`, etc. → potenziell stale.
  - Risiko: `invalidate_from()` ist implementiert aber wird hier nicht automatisch aufgerufen. Tester sollte prüfen ob das finale Video noch konsistent ist.
- [ ] **2.2.3 Final.mp4 löschen**
  - Setup: Compose-Output `{slug}.mp4` löschen, Re-Run.
  - Expected: `is_done(COMPOSE) and out.is_file()` schlägt fehl → Compose re-runs sofort (ohne Step davor).
- [ ] **2.2.4 job_state.json komplett löschen**
  - Setup: Resume an, ein Run fertig. State-File komplett löschen. Re-Run.
  - Expected: Full re-render, kein Crash. Genauso wie ein Erst-Run.

### 2.3 Spec-Hash-Drift

- [ ] **2.3.1 Target-Duration ändern**
  - Setup: Lauf 1 mit `target_duration=30`, Lauf 2 mit `target_duration=45` (gleicher Slug, Resume an).
  - Expected: WARN-Log `resume: job parameters changed since last run (hash A → B); completed steps will still be reused — delete job_state.json to force a full re-render`. Steps werden trotzdem aus Cache geladen.
  - Risiko: User-Erwartung könnte sein "Pipeline rendert neu mit 45s" — das passiert NICHT. Doku in der Warnung steht klar, aber UX-mäßig fragwürdig.
- [ ] **2.3.2 Hook-Text geändert**
  - Setup: Lauf 1 ohne Hook, Lauf 2 mit Hook-Text. Resume an, gleicher Slug.
  - Expected: Spec-Hash-Warning. Compose-Step ist im Cache → Hook erscheint NICHT im finalen Video.
  - Risiko: User vergisst dass er State-File löschen muss. **Empfehlung:** GUI-Hinweis hinzufügen oder Hook-Änderung soll Compose invalidieren.
- [ ] **2.3.3 Spec-Hash bleibt gleich bei batch_count**
  - Setup: Lauf 1 mit batch_count=1, Lauf 2 mit batch_count=3. Resume an.
  - Expected: KEINE Warning (batch_count ist NICHT in `_SPEC_KEYS_FOR_HASH`). Korrekt — batch_count ist Steuerfeld, kein Output-Param.

### 2.4 Multi-Clip Resume

- [ ] **2.4.1 Crash nach Clip 3 von 7**
  - Setup: Resume an, Multi-Clip mit 7 Clips. Während Clip 4 rendert → `Ctrl+C`. Re-Run.
  - Expected: Log: `multiclip resume: X/4 steps complete`. MULTI_DOWNLOAD, MULTI_TRANSCRIBE, MULTI_MOMENTS skipped. Clips 1-3 als "cached" angezeigt, Render startet ab Clip 4.
  - Achtung: Clip 4 selbst war im Subclip-State `pending` (oder ist im run_one-State mittendrin) → läuft komplett bzw. teilweise neu (über sub_job["resume"]=true).
- [ ] **2.4.2 Sub-Clip-Status "failed" beim Re-Run**
  - Setup: Resume an, Multi-Clip mit 5 Clips. Künstlich Clip 3 fehlschlagen lassen (z.B. invaliden manuellen Range injizieren, oder Gemini-Key kurz invalidieren). Re-Run mit gültigem Setup.
  - Expected: **REVIEWER-NOTIZ:** In `run_multiclip` Zeile 2757-2765 wird nur bei `status == "done"` und existierender Datei übersprungen. Bei `status == "failed"` läuft Clip NICHT durch die Skip-Branch → er wird beim Re-Run **retry'd**. Bestätigen.
  - Risiko: Wenn Failure deterministisch ist (z.B. Range ungültig), wird er beim Re-Run wieder failen → unendliche Retry-Schleife denkbar wenn User nicht aufpasst. Tester muss prüfen ob Failure-Reason im State-File geloggt ist.
- [ ] **2.4.3 Sub-Clip mit eigenem run_one-Resume mittendrin**
  - Setup: Während Clip 5 von 7 rendert, im Sub-Step (z.B. Image-Generation) Ctrl+C. Re-Run.
  - Expected: Multi-Clip-State sagt: Clips 1-4 done, Clip 5 pending. run_one für Clip 5 hat eigenes `job_state.json` → der lädt seinerseits den Sub-Step-Cache. Image-Generation skipped wenn bereits Bilder generiert waren.
- [ ] **2.4.4 Alle Sub-Clips done → MULTI_RENDER markiert**
  - Setup: Multi-Clip durchläuft komplett ohne Crash. Re-Run (gleicher Slug, Resume an).
  - Expected: Alle 4 Multi-Steps cached. Loop iteriert über Moments, jeder Sub-Clip als "cached" gemeldet. **Risiko:** `state.mark_done(MULTI_RENDER)` wird nur gesetzt wenn `len(outputs) == len(moments)` — falls EIN Clip via try/except continued, MULTI_RENDER bleibt unmarkiert. Tester prüfen ob Re-Run dann den ausgefallenen retry'd.
- [ ] **2.4.5 Multi-Clip Resume-Flag propagiert an Sub-Jobs**
  - Setup: Multi-Clip mit Resume an. Während Clip 2 mittendrin abbrechen (z.B. nach Voiceover). Re-Run.
  - Expected: Sub-Job-Run von Clip 2 lädt seinen eigenen State und überspringt Download + Voiceover. (`sub_job["resume"] = resume_enabled` in Zeile 2784.)
- [ ] **2.4.6 Source-File Cache funktioniert auch ohne Resume**
  - Setup: Resume AUS, Multi-Clip mit 3 Clips.
  - Expected: Source wird genau 1× geladen, Clips re-using `sub_job["source_file"]`. **Regression-Verifikation:** Pre-Merge-Verhalten unverändert.

### 2.5 Resume = OFF Verhalten

- [ ] **2.5.1 State-File aus altem Run wird ignoriert**
  - Setup: Lauf 1 mit Resume an (State-File entsteht). Lauf 2 mit Resume aus, gleicher Slug.
  - Expected: Pipeline rendert komplett neu, `job_state.json` wird NICHT geöffnet, NICHT überschrieben. Datei bleibt vom Lauf 1 stehen.
- [ ] **2.5.2 Kein State-Write bei Resume aus**
  - Setup: Frischer Slug, Resume aus.
  - Expected: Im Slug-Ordner NIE ein `job_state.json` entsteht.

---

## 3. YouTube-Optimizer-Tests (`youtube_metadata: true`)

### 3.1 Provider-Reihenfolge

- [ ] **3.1.1 Gemini wird verwendet (Primary)**
  - Setup: Gemini-Key gültig, Cloudflare optional. YT-Metadata an.
  - Expected: Log: `youtube_optimizer: metadata via gemini`. Sidecar enthält Gemini-stil Titel.
- [ ] **3.1.2 Cloudflare-Fallback**
  - Setup: `gemini_api_key` in config.json temporär leeren. Cloudflare-Keys gültig.
  - Expected: Log: `youtube_optimizer: metadata via cloudflare`. Sidecar erzeugt.
- [ ] **3.1.3 Template-Fallback (alle LLMs aus)**
  - Setup: Beide API-Keys leeren (oder Netzwerk killen via `pktcap`/`netsh`).
  - Expected: Log: `youtube_optimizer: no LLM available, using template`. `{slug}.youtube.json` enthält template-Title (=topic), 6+ template-Tags (`shorts`, `roblox`, `gaming`, `viral`, `fyp`, `trending` + Topic-Wörter). Pipeline DARF NICHT crashen.
  - Risiko: Wenn `topic` leer ist, fällt Template auf "Neuer Short" zurück. Prüfen ob das gewünscht ist.
- [ ] **3.1.4 Gemini gibt fehlerhaftes JSON zurück**
  - Setup: Schwer reproduzierbar — Mock-Run mit `_parse_json_loose("xxx")` per Python-Konsole testen.
  - Expected: `_parse_json_loose` returnt None → Fallback auf Cloudflare. Pipeline DARF NICHT crashen.

### 3.2 Thumbnail

- [ ] **3.2.1 Thumbnail an**
  - Setup: YT-Metadata an, Thumbnail-Checkbox an, Cloudflare-Keys gültig.
  - Expected: `{slug}_thumb.png` in Work-Dir. `meta.thumbnail_path` in JSON-Sidecar gesetzt.
- [ ] **3.2.2 Thumbnail aus**
  - Setup: YT-Metadata an, Thumbnail-Checkbox AUS.
  - Expected: KEIN PNG erzeugt. Sidecar-JSON enthält `"thumbnail_path": null`. `youtube.txt` zeigt KEINEN "THUMBNAIL FILE"-Block.
- [ ] **3.2.3 Cloudflare-Flux-Down → Pollinations-Fallback**
  - Setup: Thumbnail an, Cloudflare-Token invalidieren.
  - Expected: `thumbnail: cloudflare failed (...)` → `thumbnail: pollinations -> {slug}_thumb.png`. Datei trotzdem vorhanden.
- [ ] **3.2.4 Beide Image-Provider down**
  - Setup: Cloudflare leer, Pollinations gemockt-down (DNS-Block).
  - Expected: `thumbnail: pollinations failed`. Pipeline läuft weiter, `thumbnail_path` bleibt `null`. Compose nicht beeinträchtigt.

### 3.3 Sprache

- [ ] **3.3.1 Sprache "auto"**
  - Setup: Deutsches Skript, `youtube_lang=auto`.
  - Expected: Gemini-Prompt enthält KEINEN expliziten Sprach-Hint (siehe `_build_user_prompt`). Gemini erzeugt deutsche Metadaten (auf Basis Skript).
- [ ] **3.3.2 Sprache "de"**
  - Setup: Englisches Skript, `youtube_lang=de`.
  - Expected: Prompt hat `Sprache: de.`. Title ist deutsch, auch wenn Skript englisch.
- [ ] **3.3.3 Sprache "en"**
  - Setup: Deutsches Skript, `youtube_lang=en`.
  - Expected: Prompt enthält `Sprache: en.`. Title englisch.

### 3.4 Sidecar-Files

- [ ] **3.4.1 JSON-Sidecar valide**
  - Setup: Beliebigen Run mit YT-Metadata.
  - Expected: `{slug}.youtube.json` ist gültiges JSON (`python -m json.tool` schlägt nicht fehl). Felder: `title`, `description`, `tags` (list), `thumbnail_prompt`, `thumbnail_path` (str|null).
- [ ] **3.4.2 TXT-Sidecar lesbar**
  - Setup: dito.
  - Expected: `{slug}.youtube.txt` enthält 4 Sektionen: TITLE, DESCRIPTION, TAGS, THUMBNAIL PROMPT (+ optional THUMBNAIL FILE). Title-Header zeigt Längenstatus `=== TITLE (N/100) ===`.
- [ ] **3.4.3 Title-Truncation > 100 Zeichen**
  - Setup: Künstlich langen Title injizieren — z.B. ein Topic-Feld mit 200 Zeichen und Gemini-Prompt mit `MUST return long title` (oder direkt _coerce_metadata aufrufen im Repl).
  - Expected: Title in Sidecar ist ≤100 Zeichen, endet auf `...`. Logik in `_coerce_metadata` Zeile 116-117 prüfen.
  - Risiko: Prompt-Limit ist 70 in den Instructions, Coercion bei 100 — Diskrepanz! Falls Gemini sich an 70 hält, wird Coercion-Branch nie getriggert. Bewusst geprüft.
- [ ] **3.4.4 `#Shorts` immer in Description**
  - Setup: 3 Runs mit verschiedenen Skripten.
  - Expected: Jede `description` enthält case-insensitive `#shorts` (Logik Zeile 143-144).
- [ ] **3.4.5 Tags-Count im erwarteten Bereich**
  - Setup: dito.
  - Expected: 6 ≤ `len(tags)` ≤ 15. Keine Duplikate. Keine `#` als Präfix. Alle lowercase.
- [ ] **3.4.6 UTF-8 mit Sonderzeichen**
  - Setup: Deutscher Skript mit Umlauten + Emojis.
  - Expected: JSON-Sidecar mit `ensure_ascii=False` → Umlaute roh sichtbar. TXT-Datei in UTF-8.

### 3.5 Multi-Clip + YT-Metadata

- [ ] **3.5.1 Pro Sub-Clip eigenes Sidecar**
  - Setup: Multi-Clip mit 3 Clips + YT-Metadata an.
  - Expected: 3× `.youtube.json` + 3× `.youtube.txt`. Jeder Sub-Clip eigene Metadaten basierend auf seinem Skript.
  - Risiko: Sub-Jobs werden in `run_multiclip` via `sub_job = dict(job)` kopiert — `youtube_metadata` wird durch `dict(job)` propagiert. Verifizieren.

### 3.6 Upload-Stub

- [ ] **3.6.1 upload_to_youtube ist NICHT aus GUI aufrufbar**
  - Setup: GUI durchsuchen nach Upload-Button.
  - Expected: KEIN Upload-Button vorhanden. Bewusst (Sidecar-Review zuerst).
- [ ] **3.6.2 upload_to_youtube ohne Lib → klare Fehlermeldung**
  - Setup: Python-Repl: `from youtube_optimizer import upload_to_youtube; upload_to_youtube(Path("x.mp4"), meta)`.
  - Expected: RuntimeError mit Pip-Install-Anweisung (Zeile 416-421). KEIN nackter ImportError.

---

## 4. Auto-Reframe-v2-Tests (`reframe_v2: true` und `auto_reframe: true`)

### 4.1 Flag-Kombinationen

- [ ] **4.1.1 v2 aus + Reframe an → v1 läuft**
  - Setup: Auto-Reframe an, v2 aus.
  - Expected: Log: `auto-reframe: per-scene detection ...` ODER `auto-reframe: asking Cloudflare Vision`. KEIN `auto-reframe v2:`. Regression bestätigt.
- [ ] **4.1.2 v2 an + Reframe AUS → nichts läuft**
  - Setup: Auto-Reframe AUS, v2 AN.
  - Expected: Reframe-Block in pipeline.py Zeile 3271 (`elif bool(job.get("auto_reframe", False))`) wird übersprungen → `crop_offset=0.5`. Kein v2-Log. **WICHTIG:** v2 ist Sub-Toggle, kein eigenständiges Feature.
- [ ] **4.1.3 Beide an**
  - Setup: Auto-Reframe an, v2 an, Single-Clip auf Video (a).
  - Expected: Log: `auto-reframe v2: per-scene tracking (N seg × Xs)`. Pro Segment Log-Zeile mit `crop@XX%(label)`.

### 4.2 Inhaltliche Korrektheit

- [ ] **4.2.1 Single-Speaker links im Bild → Offset < 0.5**
  - Setup: Video (a), Speaker hauptsächlich links. v2 an, Single-Clip.
  - Expected: Final-Offset (Median über Segmente) < 0.4. Visual-Check: rechte Seite wird gecropped, Sprecher voll sichtbar.
- [ ] **4.2.2 Single-Speaker rechts → Offset > 0.5**
  - Setup: gleiches Video, anderer Cut wo Speaker rechts ist.
  - Expected: Offset > 0.6.
- [ ] **4.2.3 Speaker wandert links→rechts (v2 vs v1 Vergleich)**
  - Setup: Cut mit klarer L→R-Bewegung. Run 1 mit v1, Run 2 mit v2 (verschiedene Slugs).
  - Expected: v1 mittelt → mittlerer Offset, beide Ränder evtl. angeschnitten. v2 schickt pro Segment unterschiedlichen Offset → Crop folgt Speaker. Visual-Side-by-Side bestätigen.
- [ ] **4.2.4 Podcast-Layout (2 Personen seitlich)**
  - Setup: Video (b), 2 Speaker links/rechts. v2 an.
  - Expected: Log-Labels enthalten `+multi`. Offsets liegen näher an 0.5 als v1 sie hätte (siehe `_pick_subject_offset` Zeile 254-255: `offset = 0.5 + 0.65 * (offset - 0.5)`).
  - Risiko: Wenn `multi_face` nicht erkannt wird (Detector findet nur 1 Face), läuft Standard-Logik. Tester soll prüfen ob YOLO beide Personen erkennt.
- [ ] **4.2.5 Video komplett ohne Gesichter**
  - Setup: Video (c), reines Gameplay, kein menschliches Gesicht. v2 an.
  - Expected: Alle Segmente Label `no-face` (oder `held-prev` nach Smoothing). Final-Offset = 0.5 (zentriert). KEIN LLM-Halluzinations-Crop. **Wichtig:** Auch keine Cloudflare-Vision-Anfrage (das wäre v1-Behavior).
- [ ] **4.2.6 Speaker dreht kurz weg (Hold-Last)**
  - Setup: Cut wo Speaker für ~1 Segment das Gesicht abwendet, danach wieder zur Kamera.
  - Expected: Mittleres Segment-Label `held-prev`, Offset = Vorgänger-Offset. KEIN Sprung zu 0.5. Verifizieren via Log-Zeile mit Offsets pro Segment.
- [ ] **4.2.7 No-Face am Anfang (Hold-Next-Backfill)**
  - Setup: Cut der mit Establishing-Shot ohne Gesicht beginnt, dann Speaker.
  - Expected: Erste Segmente Label `held-next` mit Offset des ersten echten Detection-Segments.

### 4.3 Samples-pro-Segment Slider

- [ ] **4.3.1 Samples=1 vs Samples=7 (Speed)**
  - Setup: Gleicher Clip 2× mit verschiedenen Slider-Werten. Stoppuhr.
  - Expected: Samples=1 ~7× schneller als Samples=7 (lineare Skalierung mit ffmpeg-Calls).
- [ ] **4.3.2 Samples=1 → Stabilität schlechter**
  - Setup: Clip mit Motion-Blur in der Mitte eines Segments.
  - Expected: Samples=1 evtl. `no-face` → held-prev. Samples=3+ findet mind. 1 gutes Frame → echter Offset.
- [ ] **4.3.3 Slider clamping**
  - Setup: Job-Dict manuell mit `reframe_samples_per_seg=0` oder `100` injizieren.
  - Expected: `max(1, min(int(samples_per_segment), 7))` clamped → effektiv 1 bzw. 7. Keine Exception.

### 4.4 Multi-Clip + v2

- [ ] **4.4.1 v2 propagiert nicht an Sub-Jobs**
  - Setup: Multi-Clip mit Resume an, v2 an.
  - Expected: **REVIEWER-NOTIZ:** In `run_multiclip` Zeile 2784 wird nur `resume` propagiert (`sub_job["resume"] = resume_enabled`). `reframe_v2` ist NICHT explizit gesetzt. Aber `sub_job = dict(job)` (Zeile 2768) kopiert ALLE Felder, also auch `reframe_v2`. Verifizieren dass Sub-Clips v2 nutzen.
- [ ] **4.4.2 Multi-Clip mit unterschiedlichen Speakern pro Sub-Clip**
  - Setup: Multi-Clip auf Podcast-Video, einige Cuts mit Speaker links, andere rechts. v2 an.
  - Expected: Pro Sub-Clip eigene `[5/5]`-Log-Zeile mit v2-Offsets, jeder Clip korrekt gecropped.

### 4.5 Detector-Kaskade

- [ ] **4.5.1 YOLOv11 ist primary**
  - Setup: YOLOv11-weights vorhanden (`yolov11s-face.pt`).
  - Expected: Log-Labels mehrheitlich `yolo`. (`Detection.detector == "yolo"`.)
- [ ] **4.5.2 YOLO entfernen → InsightFace fallback**
  - Setup: YOLO-Weights temporär umbenennen.
  - Expected: Labels = `insightface` (falls installiert) oder `mediapipe`.
- [ ] **4.5.3 Beide hochstufigen Detectors aus → MediaPipe**
  - Setup: YOLO + InsightFace deaktivieren (z.B. uninstall ultralytics).
  - Expected: Labels = `mediapipe`. Pipeline läuft, aber langsamer (CPU).

---

## 5. Edge Cases

### 5.1 Filesystem

- [ ] **5.1.1 Output-Dir existiert nicht**
  - Setup: `output_dir` in config.json zeigt auf nicht-existierenden Pfad (z.B. `D:\Neuer\Pfad`).
  - Expected: `mkdir(parents=True, exist_ok=True)` in pipeline.py erstellt Pfad. Run läuft.
- [ ] **5.1.2 State-File korrupt (manuell zerstört)**
  - Setup: Resume an, vorhandenes `job_state.json` mit Müll überschreiben (`echo "{not json" > job_state.json`). Re-Run.
  - Expected: WARN-Log `job_state.json unreadable (...); starting fresh`. Pipeline läuft komplett neu. Kein Crash. (Logik state_manager.py Zeile 234-239.)
- [ ] **5.1.3 State-File mit fremdem job_kind**
  - Setup: State-File von Single-Clip-Run, dann Multi-Clip starten mit gleichem Slug-Pfad.
  - Expected: WARN `resume: job kind changed ('single' → 'multiclip'); starting fresh`.
- [ ] **5.1.4 Disk-Voll während State-Save**
  - Setup: Schwer simulierbar — alternativ Schreibrechte auf Slug-Ordner entziehen.
  - Expected: `state_manager.save()` fängt Exception, loggt WARN `failed to persist job_state.json: ...`. Pipeline läuft weiter (Step wird nur nicht persistiert → re-runs beim nächsten Mal, akzeptabel).
- [ ] **5.1.5 Atomic-Write verifizieren**
  - Setup: Manuell prüfen ob bei jedem Save ein `.tmp`-File entsteht und atomar umbenannt wird.
  - Expected: Niemals halbfertiges `job_state.json` auf Disk. (Logik state_manager.py Zeile 266-272.)
- [ ] **5.1.6 Spec-Hash bei Path-Werten**
  - Setup: `image_paths` enthält absolute Pfade. Hash über `default=str` (state_manager.py Zeile 154).
  - Expected: Pfade serialisierbar, Hash stabil bei gleichem Input.

### 5.2 Concurrency / Doppelter Run

- [ ] **5.2.1 2× Multi-Clip mit gleichem Slug parallel**
  - Setup: GUI in zwei Tabs öffnen, beide starten Multi-Clip mit identischem Slug.
  - Expected: **Race-Condition wahrscheinlich.** Beide schreiben in dasselbe `job_state.json`. Letzter Schreiber gewinnt. Pipeline kann verwirrt sein über cached vs frische Artefakte.
  - Risiko: Kein File-Locking. **Empfehlung:** GUI sollte Slug-Sperre haben oder Lockfile schreiben (`{slug}.lock`).
- [ ] **5.2.2 Single-Clip Run während Multi-Clip mit selbem base_slug läuft**
  - Setup: Multi-Clip läuft mit `slug=foo`. Parallel Single-Clip mit `slug=foo`.
  - Expected: Multi-Clip nutzt `{output}/foo__multiclip_work/`. Single-Clip nutzt `{output}/foo/`. Pfade kollidieren NICHT. OK.

### 5.3 Eingabe-Validierung

- [ ] **5.3.1 Resume-Flag ohne Slug**
  - Setup: Job-Dict ohne `slug` an run_one übergeben.
  - Expected: KeyError "slug" beim Zugriff `job["slug"]` (Zeile 2833). Pre-existing Verhalten, nicht durch Resume verschlechtert.
- [ ] **5.3.2 Job-Spec mit None-Werten**
  - Setup: `job["topic"] = None`, alles andere Default.
  - Expected: `_hash_spec` mit `default=str` → "null" im JSON. Hash stabil. KEIN Crash.

---

## 6. GUI-Integration

### 6.1 Controls sichtbar

- [ ] **6.1.1 Auto-Reframe-Sektion**
  - Setup: GUI starten, "Auto-Reframe"-Bereich aufklappen.
  - Expected: Checkbox `⚡ Auto-Reframe v2` + Slider `Samples pro Segment (v2)` sichtbar (gui.py Zeile 374-386).
- [ ] **6.1.2 Resume & Logging Accordion**
  - Setup: Accordion `🔄 Resume & Logging` aufklappen.
  - Expected: Checkbox `♻️ Resume aktiv` (default OFF) + Dropdown `Log-Level` (default INFO).
- [ ] **6.1.3 YouTube Optimizer Accordion**
  - Setup: Accordion `📈 YouTube Optimizer` aufklappen.
  - Expected: Checkbox `📝 YouTube-Metadaten generieren` (default OFF) + Checkbox `🖼️ Thumbnail-Bild dazu generieren` (default ON, nur wirksam wenn Metadaten an) + Dropdown `Sprache` (default `auto`).

### 6.2 Defaults

- [ ] **6.2.1 Resume default OFF**
  - Setup: GUI startet frisch.
  - Expected: `value=False` bei `resume_enabled` (gui.py Zeile 574). User wird NICHT überrascht von State-Files in Slug-Ordnern.
- [ ] **6.2.2 v2 default OFF**
  - Expected: `value=False` bei `reframe_v2` (Zeile 375). Klassisches v1-Verhalten wenn unangetippt.
- [ ] **6.2.3 youtube_metadata default OFF**
  - Expected: `value=False` (Zeile 593). Keine API-Calls ohne expliziten Opt-in.
- [ ] **6.2.4 youtube_thumbnail default ON**
  - Expected: `value=True` (Zeile 603). Wenn YT-Metadata an, dann auch Thumbnail (kann der User abschalten).

### 6.3 Verdrahtung Job-Dict

- [ ] **6.3.1 Alle 7 neuen Felder im Job-Dict**
  - Setup: GUI-Run starten, in `pipeline.run_one` einen Breakpoint setzen und Job-Dict inspizieren (alternativ `print(job)` injizieren).
  - Expected: `resume`, `log_level`, `reframe_v2`, `reframe_samples_per_seg`, `youtube_metadata`, `youtube_thumbnail`, `youtube_lang` ALLE vorhanden (gui.py Zeile 154-160).
- [ ] **6.3.2 Sprache wird durchgereicht**
  - Setup: GUI Dropdown auf "Deutsch" → Run.
  - Expected: Job-Dict `youtube_lang="de"`, `_build_user_prompt` enthält `Sprache: de.`.
- [ ] **6.3.3 Log-Level wirkt auf Console**
  - Setup: Run 1 mit Log-Level=DEBUG, Run 2 mit Log-Level=WARN.
  - Expected: DEBUG-Run zeigt detaillierte Detector-Entscheidungen (`Logger.debug()`-Zeilen). WARN-Run zeigt nur Warnungen und Errors. Sichtbarer Unterschied im Console-Output.
  - Risiko: Bestehende `step()`-Calls in pipeline.py rufen NICHT über Logger sondern direkt — Log-Level betrifft nur die NEUEN `log.info/warn/debug`-Zeilen. Korrekt dokumentiert?
- [ ] **6.3.4 Slider-Wert clamped wenn typisch**
  - Setup: Slider auf 3, Run starten.
  - Expected: Job-Dict `reframe_samples_per_seg=3` (int, nicht float).

### 6.4 UX-Hints

- [ ] **6.4.1 v2-Info-Text erwähnt Auto-Reframe-Abhängigkeit**
  - Expected: `info=` Text in Zeile 377-380 sagt klar "Nur wirksam wenn Auto-Reframe oben angehakt ist".
- [ ] **6.4.2 Resume-Info erklärt Slug-basiert**
  - Expected: Info-Text erwähnt `{output_dir}/{slug}/job_state.json` und Multi-Clip-Verhalten.

---

## 7. Performance / Stress

- [ ] **7.1 Resume State-Save Overhead**
  - Setup: 10 Single-Clip-Runs mit Resume aus + 10 mit Resume an, gemittelt.
  - Expected: Resume-Overhead < 1s gesamt pro Run (10× File-Write je ~50ms).
- [ ] **7.2 v2 Reframe-Zeit bei 8 Segmenten × 3 Samples**
  - Setup: 30s-Single-Clip mit v2.
  - Expected: ~24 ffmpeg-Calls + 24 Detector-Calls. Auf RTX 3080 < 3s zusätzliche Latenz akzeptabel.
- [ ] **7.3 Multi-Clip mit 15 Clips + alle Features an**
  - Setup: Max-Setting: Multi-Clip 15, Resume an, v2 an, YT-Metadata an.
  - Expected: Läuft durch. Disk-Usage pro Multi-Clip-Ordner steigt: 15× Thumbs, 15× Sidecars, 15× Sub-Clip State-Files.

---

## 8. Risiko-Heatmap (für Reviewer)

| Risiko | Wahrscheinlichkeit | Auswirkung | Test-Fall |
|---|---|---|---|
| Failed Sub-Clip retry'd endlos bei deterministischem Fehler | mittel | mittel | 2.4.2 |
| Spec-Hash-Drift: User ändert Hook, Compose cached → Hook fehlt im Video | hoch | hoch | 2.3.2 |
| Konkurrenter Multi-Clip-Run korrumpiert State | niedrig | hoch | 5.2.1 |
| v2 Multi-Face-Heuristik trifft nicht bei stark unterschiedlich großen Faces | mittel | niedrig | 4.2.4 |
| Title > 100 Zeichen via Coercion gekappt, aber Prompt sagt 70 — Diskrepanz | niedrig | niedrig | 3.4.3 |
| Logger-Prefixe leaken in Pre-Merge-Output → Regression-Test fail | niedrig | mittel | 1.1, 1.4 |
| Artefakt-Validation prüft nur `_path`/`_file` Keys → andere stale | mittel | mittel | 2.2.1 |
| MULTI_RENDER nur bei vollständigem Success markiert → partielle Erfolge re-run alle Clips | mittel | mittel | 2.4.4 |

---

## 9. Tester-Notizen

- **Reset zwischen Tests:** Slug-Ordner zwischen Tests löschen, sonst kreuzkontaminieren State-Files.
- **Logs aufbewahren:** GUI-Status-Log per Copy-Paste in `qa_logs/{test-id}.txt` archivieren — bei Bug-Reports anhängen.
- **Visual-Checks:** Reframe-Tests brauchen ein zweites Augenpaar (Frame-by-Frame im Video-Player). Nicht nur Offset-Zahl im Log.
- **API-Cost-Wachhund:** Tests mit Gemini + Cloudflare verbrauchen Free-Tier-Quota. Bei häufigem Re-Run die Quota-Dashboards im Auge behalten.
- **Reproducibility:** TTS + Image-Gen sind nicht-deterministisch. Bei Vergleichstests (1.3, 4.2.3) erst Caches via Resume nutzen oder Random-Seeds setzen.
