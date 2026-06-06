# 🎬 Bim Bam Bum – Komplette Reproduktions-Anleitung (A–Z)

> Ziel: Aus der Datei **`C:\Users\Getinho77\Downloads\Bim Bam Bum.mp4`** ein professionelles 3D-Kinder-Musikvideo
> im Cocomelon-Stil erstellen (9:16 + 16:9 + Thumbnail), vokal-synchron geschnitten.
> Diese Anleitung enthält ALLES: Tools, Downloads, Prompts, Timings, ffmpeg-Befehle, Stolperfallen.

---

## 0) VORAUSSETZUNGEN / TOOLS

| Tool | Zweck | Wo / Install |
|---|---|---|
| **ffmpeg** | Audio-Extraktion, Schnitt, Crop, Text, Mux | vorhanden: `C:\Program Files (x86)\ClipGrab\ffmpeg.exe` |
| **Python 3** + `faster-whisper` + `librosa` | Songtext-Transkription + BPM | `python -m pip install faster-whisper librosa` |
| **Google Flow** (labs.google/fx/tools/flow) | Keyframes (Nano Banana Pro) + Animation (Veo) | Browser, Konto **gentjanzuta@gmail.com** (Google **AI Pro**-Plan, ~980 Credits/Monat) |
| **Claude in Chrome** (MCP) | Flow im Browser steuern | Browser „Browser 1" verbinden |
| Schrift | drawtext-Overlays | `C:\Windows\Fonts\arialbd.ttf` → als `font.ttf` ins Projekt kopieren |

Arbeitsordner: **`C:\Users\Getinho77\Desktop\Aksion\`**

---

## 1) PHASE 1 – ANALYSE (lokal, gratis)
1. Audio extrahieren:
   `ffmpeg -i "Bim Bam Bum.mp4" -vn -ar 16000 -ac 1 bimbambum_audio.wav` (für Whisper)
2. Transkribieren mit faster-whisper (Modell `small`, Deutsch erkannt, p=0.99), 2 Durchläufe
   (1× normal, 1× mit `vad_filter=True`, `condition_on_previous_text=False` gegen Halluzinations-Loops).
3. BPM mit librosa: `librosa.beat.beat_track` → **~103 BPM**, 4/4.

**Fakten:** Länge **136,4 s (2:16)**, **824×1464 (9:16)**, Original nur 10 fps, Audio 48 kHz Stereo.

**Songstruktur + ECHTE Vokal-Zeitstempel (entscheidend für Sync!):**
| Zeit (s) | Inhalt |
|---|---|
| 0–4.8 | Intro „Hey! Banna Banna komm mit!" |
| 4.8–9.3 | Hook „Banna Banna – Bim Bam Bum / Bum Bum Bum" |
| 14.04 | „Klatsch, Klatsch!" |
| 15.46 | „Spring hoch!" |
| 18.54 | „Dreh dich!" |
| 20.44 | „Und stopp!" |
| 23.3–27.7 | Refrain |
| 27.7–34.6 | Zählvers „Eins…sechs" |
| 37–41.6 | Refrain |
| 41.9–50 | Quatsch-Vers „Ticki ticki / La la la / Lach" |
| 51–55 | Refrain |
| 55.7–63.3 | Farbvers „Rot/Blau/Gelb/Grün" |
| 63–72 | Call&Response „Ich sag BOOM BOOM" |
| 72–124 | Großer Mitsing-/Finale-Block (Refrain ×n) |
| 124–136 | Outro „Nochmal! Nochmal!" |

---

## 2) PHASE 2–4 – KONZEPT, STORYBOARD, CHARACTER BIBLE
**Gewähltes Konzept:** „Banna's Magischer Mitmach-Zirkus" (Bewertung 9.0/10).
**Maskottchen Banna** = fröhliche **Banane als Zirkusdirektor**: roter Mantel mit Goldknöpfen, kleiner roter Zylinder,
gelbe Fliege, große Glanzaugen, zwei kleine Zähne, kleine bunte Trommel.
**Nebenfiguren:** Junge **Tom** (gelbes Shirt, blaue Latzhose), Mädchen **Lina** (türkises Kleid, zwei Zöpfe),
Babyelefant **Pim** (hellblau), Papagei **Polly** (regenbogen).
**Stil:** 3D, Cocomelon/Pixar-Junior, weich, glänzend, satte Farben, runde Zirkusbühne + Zelte.
**Lip-Sync-Regel:** Beat-Sync (lose, wie Cocomelon); **nur Banna „singt"** (offener Mund), Kinder tanzen/klatschen.

---

## 3) PHASE 6 – KEYFRAMES in Google Flow (Nano Banana Pro, GRATIS)
**WICHTIG:** In Flow → Bild → Modell **„Nano Banana Pro"** wählen (NICHT „Nano Banana 2" → macht 2D!),
9:16, kostet **0 Credits**. Pro 3D-Look.

**Universal-Prompt-Vorlage (3D erzwingen):**
> „Pixar-style 3D rendered CGI animation, Cocomelon look, glossy smooth 3D models, soft volumetric studio lighting,
> vibrant saturated colors, highly detailed 3D render, vertical 9:16. NOT 2D, not flat, not hand-drawn."

**Pro Szene (16 Keyframes), Kernbeschreibung anhängen:**
- **S01 Intro:** banana mascot Banna (red ringmaster coat, gold buttons, tiny red top hat, yellow bow tie, big glossy eyes, two teeth, toy drum) jumping into a spotlight, **wide open singing mouth**, red curtains opening, golden confetti.
- **S02 Klatsch:** boy (yellow shirt, blue dungarees) + girl (turquoise dress, two braids) clapping, star sparkles, round circus stage.
- **S03 Spring:** boy, girl, Banna jumping high, colorful balloons rising, dust puffs.
- **S04 Dreh:** girl pirouette, dress swirling, Banna spinning, swirl trails.
- **S05 Stopp:** boy, girl, Banna frozen in funny poses, big glossy red exclamation mark above.
- **S06 Refrain (Leitmotiv):** Banna drumming center, boy + girl dancing each side, four colored spotlights (red/blue/yellow/green), music notes + confetti.
- **S07 Zählvers:** glowing numbers 1–6 in a row, baby elephant juggling, Banna pointing, „counting" scene.
- **S09 Quatsch:** rainbow parrot looping, soap bubbles, Banna laughing (open mouth), silly.
- **S10 Rot:** RED spotlight floods scene, Banna drumming (open singing mouth), red balloon + confetti.
- **S11 Blau:** BLUE spotlight, baby elephant splashing blue water stars.
- **S12 Gelb:** YELLOW spotlight, boy + girl clapping, yellow star sparks.
- **S13 Grün:** GREEN spotlight, boy/girl/Banna big group jump, green leaf confetti.
- **S14 BOOM:** Banna hitting big drum (open singing mouth), glowing shockwave rings toward camera, parrot beside.
- **S16 Ensemble:** wide shot, Banna singing center, boy/girl/elephant/parrot dancing, balloon swarm.
- **S17 Finale:** Banna drumming/singing center, whole cast jumping, huge confetti firework, pulsing spotlights.
- **S19 Outro:** Banna + whole cast waving at camera, glowing play/replay button above, red curtains half-closing.

→ Qualität ≥9/10 behalten, sonst neu würfeln. (x2 generieren, beste wählen.)

---

## 4) PHASE 7 – ANIMATION in Google Flow (Veo 3.1 Fast)
In Flow → **Video → Frames → 9:16 → 1x → Modell „Veo 3.1 - Fast"** = **20 Credits/Clip**, 8 s, 720×1280, 24 fps, MIT Ton + kleinem „Veo"-Wasserzeichen unten rechts.
- Startbild = den jeweiligen Keyframe aus „Bilder" wählen („Zum Prompt hinzufügen").
- **Pipelining:** Flow stellt Videojobs in die Warteschlange → mehrere nacheinander anstoßen, ohne auf jeden zu warten.
- 16 Clips × 20 = **~320 Credits** (im AI-Pro-Plan enthalten, kein Aufpreis).

**Animations-Prompts (Bewegung, Beat-tauglich, Banna offener Mund):** je Szene „… bobbing/dancing to the beat,
smooth lively children's TV animation". Beispiele:
- S06: „Banna drums to a steady upbeat rhythm, bobbing; boy and girl dance and clap; colored spotlights sweep; confetti; subtle camera push-in."
- S14: „Banna hits the big drum hard with open singing mouth; glowing shockwave rings pulse toward camera on each beat; parrot flaps; energetic."
- S17: „Climactic finale: Banna drums and sings center; cast jumps; huge confetti firework bursts; pulsing spotlights."
- (analog für alle anderen Szenen mit ihrer Aktion)

**Clips herunterladen (über Claude in Chrome):**
1. In Flow „Videos"-Ansicht; Video-URLs per JS sammeln: `document.querySelectorAll('video')` → `getMediaUrlRedirect?name=<UUID>`.
2. Pro UUID: zweiten Tab zu `https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=<UUID>` navigieren + 3 s warten →
   Tab-Kontext zeigt **signierte URL** `https://flow-content.google/video/<UUID>?Expires=…&Signature=…`.
3. Mit PowerShell laden: `Invoke-WebRequest -Uri "<signierte URL>" -OutFile "clips\<UUID>.mp4"`.
   (Signierte URLs laufen nach ~10–15 min ab → zügig laden.)

**UUID → Szene Map (dieses Projekt):**
S01=23a5e5fb · S02=b40ef161 · S03=91d7427b · S04=9ac89544 · S05=40d274aa · S06(Refrain)=refrain_099fd3ff ·
S07=27bc41dc · S09=5ffe594a · S10=8b56a9ee · S11=cf723058 · S12=1c3ec439 · S13=0cfdea98 · S14=98380aab ·
S16=396c8563 · S17=50c755b6 · S19=c99a40fb
(Bei Neuerstellung haben die Clips NEUE UUIDs → über Standbild der ersten Frame jedem Szene zuordnen:
`ffmpeg -ss 1 -i clip.mp4 -frames:v 1 thumb.jpg` und ansehen.)

---

## 5) PHASE 8 – SCHNITT (VOKAL-SYNCHRON!) mit ffmpeg, lokal/gratis

**Kernprinzip:** Jede Szene auf ihren ECHTEN Gesangs-Zeitpunkt schneiden (siehe Tabelle Phase 1), NICHT gleichmäßig.
Clips sind 8 s; pro Segment mit `-t <Dauer>` zuschneiden; für Slots >8 s `-stream_loop 1 -t <Dauer>` (Loop).

**Finale, geprüfte Segment-Liste (Summe = 136 s):**
| # | Szene (Clip) | Dauer s | Video-Zeit |
|---|---|---|---|
| 1 | S01 | 5.0 | 0–5 (Intro) |
| 2 | S06 (Hook, **Loop auf 9 s**) | 9.0 | 5–14 |
| 3 | S02 | 2.0 | 14–16 (Klatsch) |
| 4 | S03 | 2.5 | 16–18.5 |
| 5 | S04 | 1.9 | 18.5–20.4 |
| 6 | S05 | 2.6 | 20.4–23 |
| 7 | S06 | 4.7 | 23–27.7 (Refrain) |
| 8 | S07 | 6.9 | 27.7–34.6 (Zählvers) |
| 9 | S06 | 7.0 | 34.6–41.6 |
| 10 | S09 | 8.0 | 41.6–49.6 (Quatsch) |
| 11 | S06 | 5.4 | 49.6–55 |
| 12 | S10 | 2.1 | 55–57.1 (Rot) |
| 13 | S11 | 2.1 | 57.1–59.2 (Blau) |
| 14 | S12 | 2.0 | 59.2–61.2 (Gelb) |
| 15 | S13 | 2.1 | 61.2–63.3 (Grün) |
| 16 | S14 | 8.0 | 63.3–71.3 (BOOM) |
| 17 | S16 | 8.0 | 71.3–79.3 (Finale) |
| 18 | S17 | 8.0 | 79.3–87.3 |
| 19 | S06 | 8.0 | 87.3–95.3 |
| 20 | S03 | 8.0 | 95.3–103.3 |
| 21 | S13 | 8.0 | 103.3–111.3 |
| 22 | S14 | 8.0 | 111.3–119.3 |
| 23 | S16 | 4.7 | 119.3–124 |
| 24 | S19 | 8.0 | 124–132 (Outro) |
| 25 | S19 | 4.0 | 132–136 |

**So bauen:** jedes Segment einzeln re-encoden (einheitlich), dann concat:
```
# pro Segment (Beispiel Slot 1, S01 5s):
ffmpeg -y -i clips\<S01>.mp4 -t 5.0 -an -c:v libx264 -r 24 -pix_fmt yuv420p \
  -vf "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1" seg2\s00.mp4
# Loop-Slot (S06 9s):  zusätzlich  -stream_loop 1  VOR  -i
ffmpeg -y -stream_loop 1 -i clips\<S06>.mp4 -t 9.0 -an -c:v libx264 -r 24 -pix_fmt yuv420p -vf "...wie oben..." seg2\s01.mp4
# concat.txt mit  file 'seg2/s00.mp4' …  dann:
ffmpeg -y -f concat -safe 0 -i concat3.txt -c copy _retimed2.mp4
```

---

## 6) PHASE 8b – CROP (Wasserzeichen weg) + TITEL + MITSING-TEXT + TON (1 Durchgang)

**Wichtig – Crop SYMMETRISCH/zentriert** (sonst Bild außermittig): `crop=iw*0.90:ih*0.90` (zentriert, 9:16 bleibt),
dann `scale=720:1280`. Entfernt das „Veo"-Wasserzeichen unten rechts.

**drawtext-Fenster (auf die Vokal-Zeiten gesetzt):** Titel `lt(t,3.2)`; Hook „Banna Banna - Bim Bam Bum" `between(t,5,14)`
und `between(t,23,27.7)` und `between(t,34.6,41.6)`; Zählvers „Eins zwei drei vier fuenf sechs" `between(t,27.7,34.6)`;
Farben „Rot Blau Gelb Gruen" `between(t,55,63.3)`; „BOOM BOOM!" `between(t,63.3,71.3)`; „Nochmal! Nochmal!" `between(t,124,136)`.
Schrift: `font.ttf` (= Arial Bold). Box: `box=1:boxcolor=black@0.45:boxborderw=16`, `y=h-210`, zentriert.

```
ffmpeg -y -i _retimed2.mp4 -i "C:\Users\Getinho77\Downloads\Bim Bam Bum.mp4" \
 -filter_complex "[0:v]crop=iw*0.90:ih*0.90,scale=720:1280,setsar=1, \
   drawtext=fontfile=font.ttf:text='BIM BAM BUM':fontcolor=white:fontsize=96:borderw=5:bordercolor=black:x=(w-text_w)/2:y=170:enable='lt(t,3.2)', \
   drawtext=fontfile=font.ttf:text='Bannas Mitmach-Zirkus':fontcolor=yellow:fontsize=46:borderw=3:bordercolor=black:x=(w-text_w)/2:y=300:enable='lt(t,3.2)', \
   ... (weitere drawtext wie oben) ... [v]" \
 -map "[v]" -map 1:a:0 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest BimBamBum_FINAL_v2.mp4
```
**TON:** Audio aus der ORIGINAL-MP4 nehmen (48 kHz Stereo) – NICHT aus `bimbambum_audio.wav` (das ist nur 16 kHz mono!).

---

## 7) PHASE 9 – QC
Frames prüfen: `ffmpeg -ss <t> -i BimBamBum_FINAL_v2.mp4 -frames:v 1 qc.jpg` bei
t=4.5/5.5 (Intro-Schnitt bei 5 s), 14.5 (Klatsch), 28 (Zählvers), 56 (Farben), 67 (BOOM), 134 (Outro).
Schnitte müssen AUF den Vokalen sitzen.

---

## 8) 16:9-QUERFORMAT für YouTube (Blur-Fill)
```
ffmpeg -y -i BimBamBum_FINAL_v2.mp4 -filter_complex \
 "[0:v]split=2[bg][fg];[bg]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=28,eq=brightness=-0.08:saturation=1.1[bgb]; \
  [fg]scale=-2:1080[fgs];[bgb][fgs]overlay=(W-w)/2:0[v]" \
 -map "[v]" -map 0:a:0 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a copy BimBamBum_FINAL_YouTube_16x9.mp4
```

## 9) THUMBNAIL (1280×720)
Aus Finale-Frame: blurred Hintergrund + zentriertes Bild + „BIM BAM BUM" (Impact) + „Bannas Mitmach-Zirkus".

---

## 10) STOLPERFALLEN (unbedingt beachten)
1. **Nano Banana 2 = 2D** → für 3D **Nano Banana Pro** nehmen.
2. **Veo-Wasserzeichen** unten rechts → mit zentriertem `crop=iw*0.90:ih*0.90` entfernen (NICHT von oben-links croppen, sonst außermittig).
3. **Ton:** Original-MP4-Audio verwenden, nicht das 16-kHz-Whisper-WAV.
4. **Sync:** Szenen auf die ECHTEN Vokal-Zeitstempel schneiden (Tabelle Phase 1). Erster Schnitt bei **5 s** (auf „Banna Banna"), Klatsch bei **14 s**.
5. **Flow Browser-Upload** akzeptiert KEINE lokalen Dateien (Sandbox) → Keyframes DIREKT in Flow generieren (kein Upload nötig).
6. **Screenshots des Flow-Tabs** hängen manchmal → `read_page`/JS nutzen, Ergebnis-Bilder über signierte URL im 2. Tab ansehen.
7. **Signierte Video-URLs** laufen schnell ab → sofort herunterladen.
8. **Loop** für Slots >8 s: `-stream_loop 1` (`-t 9` allein loopt NICHT, sondern cappt bei Cliplänge).
9. drawtext: keine Emojis (Arial rendert sie nicht); für Kyrillisch/Albanisch `textfile=` (UTF-8) nutzen.

---

## 11) FINALE DATEIEN (im Ordner Aksion)
- `BimBamBum_FINAL_v2.mp4` – 9:16 (Shorts/TikTok), 2:16, vokal-synchron, Titel+Mitsing-Text, kein Wasserzeichen
- `BimBamBum_FINAL_YouTube_16x9.mp4` – 16:9 (YouTube)
- `BimBamBum_Thumbnail.jpg` – Titelbild
- `clips\*.mp4` – die 16 Roh-Clips · `seg2\*.mp4` – die geschnittenen Segmente
- `BimBamBum_Analyse_Storyboard.md` – Phasen 1–5 Doku · `Keyframe_Galerie.html` – Keyframe-Übersicht

**Budget gesamt:** Bilder gratis (Nano Banana Pro), Animation ~320 Credits (im 20-$-Google-AI-Pro-Plan enthalten),
Schnitt/Crop/Text/Formate/Thumbnail = 0 (lokal mit ffmpeg).
```
```
