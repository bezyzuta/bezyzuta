# Bezys Shorts Generator — als .exe bauen

> **Wichtig:** Eine Windows-`.exe` lässt sich **nur auf Windows** erzeugen
> (nicht aus einer Linux-/Cloud-Umgebung). Du baust sie also einmal selbst
> auf deinem PC — das ist ein Doppelklick.

## So geht's

1. Stell sicher, dass deine `.venv` eingerichtet ist und `python gui.py`
   normal läuft.
2. **Doppelklick auf `build_exe.bat`** (oder im Terminal `build_exe.bat`).
3. Warte ein paar Minuten. Ergebnis:
   ```
   dist\BezysShortsGenerator\BezysShortsGenerator.exe
   ```
4. **Doppelklick auf die `.exe`** → die App startet, ein Konsolenfenster
   zeigt den Fortschritts-Log, der Browser öffnet sich mit der GUI.

## Wie es funktioniert (kurz & ehrlich)

- Die `.exe` ist ein **schlanker Starter** für die bestehende GUI — sie
  bündelt **nicht** die schweren KI-Pakete (torch, chatterbox, whisper, …).
  Die laufen weiter aus deiner `.venv`, genau wie bei `python gui.py`.
  Grund: alles einzubacken würde die Datei mehrere GB groß machen und
  CUDA/GPU bricht dabei oft.
- Deshalb: **die `.exe` muss im Projektordner liegen** (neben `gui.py`,
  `pipeline.py`, `config.json`) bzw. der Ordner `dist\BezysShortsGenerator`
  innerhalb des Projekts bleiben. Verschiebst du sie weg, findet sie die
  `.venv` / `config.json` nicht.
- `config.json`, `ffmpeg` und die `.venv` müssen wie gewohnt vorhanden sein.

## Verknüpfung auf den Desktop

Rechtsklick auf die `.exe` → „Senden an" → „Desktop (Verknüpfung
erstellen)". Dann startest du die App künftig per Desktop-Icon.

## Wenn der Build scheitert

- Häufigste Ursache: PyInstaller findet ein dynamisch importiertes
  Gradio-Modul nicht. Die `bezys.spec` sammelt sie bereits (`collect_*`).
  Falls trotzdem ein `ModuleNotFoundError` beim Start der `.exe` kommt,
  schick mir die Fehlerzeile — dann ergänze ich den `hiddenimports`-Eintrag.
- Alternativ tut's weiterhin `start-gui.bat` / `python gui.py` — die `.exe`
  ist nur Komfort, kein Muss.
