# Bezys Shorts Generator — als .exe bauen

> **Warum kein fertiges .exe im Repo?** Eine Windows-`.exe` kann nur **auf
> Windows** gebaut werden. Du baust sie einmal selbst — ein Doppelklick.

> **Was die .exe ist:** ein **schlanker Starter** (nur Stdlib, ein paar MB).
> Sie bündelt NICHT die KI-Pakete (torch/chatterbox/whisper) — eine
> PyInstaller-exe kann deine `.venv` nicht mitbenutzen, und alles
> einzubacken wäre mehrere GB groß und würde CUDA brechen. Stattdessen
> **findet die .exe deine `.venv` + `gui.py` und startet sie** — genau wie
> `start-gui.bat`, nur als Icon. Die echte App läuft also in der `.venv`
> mit allen Abhängigkeiten.

## So baust du sie (einmalig, ~1 Min)

1. `python gui.py` muss normal laufen (`.venv` eingerichtet).
2. **Doppelklick auf `build_exe.bat`**.
3. Ergebnis: `dist\BezysShortsGenerator.exe` — wird automatisch auch direkt
   in den Projektordner kopiert (`BezysShortsGenerator.exe`).

## So startest du

- **Doppelklick auf `BezysShortsGenerator.exe`** (im Projektordner).
- Ein Konsolenfenster zeigt den Fortschritts-Log, der Browser öffnet die GUI.
- Bei einem Fehler **bleibt das Fenster offen** und zeigt die Ursache
  (kein Wegflackern mehr).

## Desktop-Icon

Rechtsklick auf `BezysShortsGenerator.exe` → „Senden an" → „Desktop
(Verknüpfung erstellen)". Künftig per Doppelklick aufs Icon starten.

## Wichtig

- Die `.exe` muss **im Projektordner** liegen (neben `gui.py`, `pipeline.py`,
  `config.json`, `.venv`) — sie sucht von ihrem Standort aus nach diesen
  Dateien. Liegt sie woanders, findet sie das Projekt nicht und sagt das im
  (offenen) Fenster.
- `ffmpeg` muss wie gewohnt im PATH sein.

## Wenn beim Start ein Fehler steht

Das Fenster bleibt jetzt offen und zeigt den echten Fehler — schick mir die
Zeilen, dann fixe ich es. `start-gui.bat` / `python gui.py` funktioniert
weiterhin als Fallback.
