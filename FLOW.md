# Google Flow (Veo) — Bild-zu-Video-Clips mit deinen Gratis-Credits

Google Flow hat **keine API** — deine kostenlosen Flow-Credits gehen nur über die
Website. Deshalb fährt der Generator **nicht** selbst Flow, sondern liefert dir
genau das, was Flow braucht, und baut hinterher das fertige Video. Zwei Schritte:

```
1) EXPORT   → Pipeline macht Skript + Stimme + Start-Bilder + Prompts
2) FLOW      → DU lässt Flow (per Extension) die Clips generieren + lädst sie runter
3) ASSEMBLE → Pipeline baut aus den Clips + der Stimme das fertige Video
```

## 1) Export
```powershell
cd C:\Users\bezy\Desktop\roblox-shorts\bezyzuta
python .venv\Scripts\python.exe -m... # ODER:
.venv\Scripts\python.exe flow_clips.py export flow.example.json
```
(`flow.example.json` anpassen — Pflicht ist nur `topic`. `output_format: "faceless"`
= 16:9 Querformat-Story, ideal für Flow-Langvideos.)

Das erzeugt einen Ordner `…\Youtube\<slug>_flow_export\` mit:
- `beat_01.png`, `beat_02.png`, … — die **Start-Bilder** pro Beat
- `prompts.txt` — eine **Image-to-Video-Prompt-Zeile** pro Beat (gleiche Reihenfolge)
- `voice.mp3` — die fertige Stimme (wird in Schritt 3 wiederverwendet)
- `beats.json` — das Manifest (Timing + Job-Snapshot, brauchst du nicht anfassen)
- `README.txt`

## 2) Flow (du, per Extension)
- Nimm eine **Flow-Automation-Extension** (z.B. „Flow Automator" / „Google Flow
  Automation" aus dem Chrome Web Store) — die schickt Bild+Prompt-Listen batch-
  weise an Flow (Veo **Image-to-Video**) und lädt die Clips in Masse runter.
- Lade die `beat_XX.png` + die Zeilen aus `prompts.txt` rein, im **richtigen
  Account** (deine Credits), generiere die Clips.
- **Lade alle Clips in EINEN Ordner.** Reihenfolge = Beat-Reihenfolge; der
  Assembler sortiert natürlich (`clip_1, clip_2, … clip_10`), also stell sicher,
  dass die Dateinamen in der richtigen Reihenfolge sortieren.

> ⚠️ Jeder Veo-Clip ist **max. 8 Sekunden** → ein 90s-Video ≈ 12-15 Clips ≈
> entsprechend Credits. AI Pro = 1000 Credits/Monat (~50 Veo-Fast-Clips). Plane
> deine Credits pro Account.

## 3) Assemble
```powershell
.venv\Scripts\python.exe flow_clips.py assemble "C:\Users\bezy\Desktop\Youtube\<slug>_flow_export" "C:\Pfad\zu\den\clips"
```
Das nimmt die Clips als Beat-Visuals, **dieselbe Stimme** aus dem Export, fügt
Captions/Effekte hinzu und rendert das fertige Querformat-Video nach
`…\Youtube\<slug>.mp4`.

## Danach hochladen
Die fertige `<slug>.mp4` kannst du normal über den Autopilot/YouTube-Upload
veröffentlichen (oder manuell). Tipp: einen Mini-Autopilot-Job mit `source`-losem
`upload` bauen — oder einfach in YouTube Studio hochladen.

## Ehrliche Grenzen
- **Halb-manuell:** Schritt 2 (Flow) machst du selbst — Flow hat keine API, das
  ist nicht vollautomatisch.
- **Credits begrenzen die Menge** — „ein paar Langvideos/Monat" pro Account.
- Die **Clip-Reihenfolge** muss stimmen (Dateinamen natürlich sortierbar). Wenn
  deine Extension wirr benennt, vorher umbenennen (`01_...mp4`, `02_...mp4`, …).
- Stimmt die Clip-Anzahl nicht exakt mit den Beats überein, ist das ok — die
  Clips werden über die Voiceover-Länge verteilt.
