# automation/ — PC steuern (Maus, Tastatur, Browser)

Eigenständiges Toolkit, das **nichts** an `pipeline.py` ändert. Drei Bausteine,
jeder für einen anderen Zweck. Die Pipeline selbst rufst du ja schon direkt
per Python auf — das hier ist für alles _außerhalb_ davon.

| Datei | Wofür | Robustheit |
|---|---|---|
| `browser.py` | Web-Apps: YouTube/TikTok-Upload, Higgsfield/Grok-Web, Logins | ✅ hoch (klickt DOM-Elemente, nicht Pixel) |
| `desktop.py` | Native Programme ohne API | ⚠️ mittel (pixel-/bild-basiert) |
| `recorder.py` | „Nimm auf was ich tue und spiel's ab" | ⚠️ niedrig (absolute Koordinaten) |

**Faustregel:** Geht es im Browser → nimm `browser.py`. Nur wenn es ein
Desktop-Programm ist, das man nicht über den Browser bedienen kann → `desktop.py`.

---

## Installation (einmalig, auf deinem Windows-PC)

In deiner venv (`C:\Users\bezy\Desktop\roblox-shorts\bezyzuta`):

```
.venv\Scripts\python.exe -m pip install -r automation\requirements-automation.txt
.venv\Scripts\python.exe -m playwright install chromium
```

Die zweite Zeile lädt Chromium für Playwright (~150 MB, einmalig). `pyautogui`
und `pynput` brauchen unter Windows nichts Extra.

---

## 1) browser.py — Web-Apps (empfohlen)

**Workflow:** Einmal pro Seite von Hand einloggen, danach ist die Session
gespeichert (`automation\.browser_profile\`, per `.gitignore` ausgeschlossen).

```
:: einmal einloggen (öffnet sichtbaren Browser, du loggst dich ein, dann ENTER)
.venv\Scripts\python.exe automation\browser.py --login https://studio.youtube.com

:: Smoke-Test (öffnet example.com, macht Screenshot)
.venv\Scripts\python.exe automation\browser.py
```

Eigenes Flow-Skript (Beispiel YouTube-Upload-Gerüst):

```python
from automation.browser import Browser

with Browser(headless=False, slow_mo_ms=200) as b:
    b.goto("https://studio.youtube.com")
    b.click("text=Erstellen")                  # oder "Create"
    b.click("text=Video hochladen")
    b.upload("input[type=file]", r"C:\Users\bezy\Desktop\Youtube\mein_short.mp4")
    b.wait_for("text=Verarbeitung abgeschlossen", timeout_s=600)
    b.shot("upload_done")
```

**Selektoren findest du live** mit `b.pause()` — öffnet den Playwright Inspector,
„Pick locator" anklicken, Element wählen, fertigen Selector kopieren. Das ist
der schnellste Weg, einen Flow zu bauen (Button-Texte/IDs ändern sich je nach
Sprache und UI-Version, deshalb hier kein hartkodierter Upload-Flow).

---

## 2) desktop.py — native Programme

Bild-verankerte Klicks sind das Robuste: mach einen kleinen Ausschnitt vom
Button (z.B. mit dem Windows-Snipping-Tool), speichere ihn unter
`automation\anchors\save_btn.png`, dann:

```python
from automation import desktop

desktop.click_image("save_btn.png", timeout_s=10)   # wartet bis sichtbar, klickt
desktop.type_text("Hallo Welt")
desktop.hotkey("ctrl", "s")
desktop.shot("nach_speichern")
```

```
:: Demo: Bildschirmgröße + Mausposition + Screenshot
.venv\Scripts\python.exe automation\desktop.py
```

**Not-Aus:** Maus blitzschnell in die **obere linke Bildschirmecke** → Skript
bricht sofort ab (pyautogui Failsafe ist an).

---

## 3) recorder.py — aufnehmen & abspielen

```
:: aufnehmen (ESC drücken = Stop)
.venv\Scripts\python.exe automation\recorder.py record mein_makro

:: abspielen (optional schneller)
.venv\Scripts\python.exe automation\recorder.py play mein_makro --speed 1.5
```

Speichert nach `automation\macros\mein_makro.json`. Funktioniert nur zuverlässig,
wenn Fenster an derselben Stelle und Auflösung gleich ist.

---

## Hinweise

- Diese Skripte laufen **nur auf deinem PC** (echte Maus/Tastatur/Bildschirm).
  In der Cloud-Session (wo ich arbeite) gibt es keinen Bildschirm — ich kann
  sie schreiben/anpassen, aber nicht ausführen.
- `.browser_profile/`, `macros/`, `shots/`, `anchors/` sind lokal und werden
  **nicht** committet (siehe `automation/.gitignore`) — deine Cookies bleiben
  auf deinem Rechner.
- Nicht Teil der `pytest`-Suite (optionale Extra-Deps). Die Hauptsuite bleibt
  unverändert.
