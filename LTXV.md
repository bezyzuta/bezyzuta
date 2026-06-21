# LTX-Video — echtes KI-Bild-zu-Video, lokal auf deiner GPU (gratis)

Animiert im **Musik-Snippet-Modus** jedes KI-Standbild zu echtem Bewegtbild
(Kamera-Push, driftendes Licht, Atmosphäre) — **kostenlos, auf deiner eigenen
RTX 3080, kein Abo**. Schlägt etwas fehl (kein venv, zu wenig VRAM, Modell
fehlt), fällt das Tool automatisch auf den Ken-Burns-Zoom des Standbilds
zurück — ein Render bricht nie ab.

## Warum ein eigener venv?

Die Diffusion-Pakete (torch/diffusers/numpy) beißen sich mit dem Chatterbox-
Stack im Haupt-venv. Darum läuft LTX-Video in einem **separaten venv** und wird
per Subprozess aufgerufen — genau wie WhisperX. Dein Haupt-venv bleibt sauber.

## Einrichtung (einmalig, ~10–15 Min)

1. **Separaten venv anlegen** (ein Ordner neben dem Projekt):
   ```
   cd C:\Users\bezy\Desktop\roblox-shorts
   python -m venv ltxv-venv
   ```

2. **Torch (CUDA) + Diffusion-Pakete installieren:**
   ```
   ltxv-venv\Scripts\python.exe -m pip install --upgrade pip
   ltxv-venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   ltxv-venv\Scripts\python.exe -m pip install "diffusers>=0.32" transformers accelerate imageio imageio-ffmpeg sentencepiece
   ```

3. **In `config.json` eintragen** (Pfad zur python.exe des neuen venv, doppelte Backslashes!):
   ```json
   "use_ltx_video": true,
   "ltxv_python": "C:\\Users\\bezy\\Desktop\\roblox-shorts\\ltxv-venv\\Scripts\\python.exe"
   ```

4. **Fertig.** Beim ersten Musik-Snippet-Lauf lädt LTX-Video einmalig das Modell
   (~mehrere GB) von HuggingFace. Danach ist es gecacht.

## Tuning für die RTX 3080 (10 GB)

Standardwerte sind konservativ gewählt (passen in 10 GB):

| config-Feld | Default | Bedeutung |
|---|---|---|
| `ltxv_width` / `ltxv_height` | 480 / 832 | Auflösung (muss durch 32 teilbar sein) |
| `ltxv_frames` | 97 | ~4 s bei 24 fps (muss 8·k+1 sein: 49, 73, 97, 121…) |
| `ltxv_steps` | 30 | mehr = besser, aber langsamer |
| `ltxv_fps` | 24 | Bildrate des Clips |

- **Out-of-Memory?** → `ltxv_width`/`ltxv_height` runter (z. B. 448/768) oder
  `ltxv_frames` auf 73/49.
- **Zu langsam / PC zu heiß?** → weniger `ltxv_steps` (20–25), weniger Frames.
  Rechne mit **~1–3 Min pro Clip** auf der 3080. 10 Clips = entsprechend lange.
- Der erzeugte Clip (~4 s) wird automatisch auf die Snippet-Länge **geloopt**.

## Ehrliche Hinweise

- **Das ist Dauer-Volllast auf der GPU.** Dein PC ist bei Volllast schon mal
  ausgegangen (Hitze/Netzteil) — behalte die Temperaturen im Auge, und nutz das
  Power-Limit/Undervolt von früher. Lieber wenige Clips am Stück.
- Qualität/Bewegung von LTX-Video ist gut, aber nicht Hollywood — für dunkle
  Musik-Snippets (leichte Kamerafahrt, Atmosphäre) ist es genau richtig.
- Wenn du es nicht einrichtest oder ausschaltest (`use_ltx_video: false`),
  läuft alles wie bisher mit dem Ken-Burns-Standbild.
