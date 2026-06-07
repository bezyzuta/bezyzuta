# DEPLOY — Video-Generator von überall erreichbar machen

Ziel: Dein Tool läuft weiter auf deinem **RTX-3080-PC zu Hause** (GPU gratis),
du greifst von Laptop/Handy/überall darauf zu. **Kosten: 0 €** — kein Server mieten.

Empfohlener Weg: **Tailscale** (privates Netzwerk, sicher, gratis).
Alternativen (Cloudflare Tunnel / Gradio-Share) stehen weiter unten.

---

## Neue Umgebungsvariablen

`gui.py` liest jetzt 3 optionale Variablen. Ohne sie ändert sich lokal **nichts**.

| Variable | Wirkung | Beispiel |
|---|---|---|
| `BEZY_HOST` | Bind-Adresse. Standard `127.0.0.1` (nur lokal). Für Remote: `0.0.0.0` | `0.0.0.0` |
| `BEZY_PORT` | Fester Port (Tunnel brauchen einen stabilen). Standard: automatisch | `7860` |
| `BEZY_AUTH` | Login `user:passwort` erzwingen (für öffentliche Wege) | `bezy:meinpasswort` |

---

## Weg 1 — Tailscale (EMPFOHLEN, 0 €, ~10 Min)

Macht ein privates Netz zwischen deinen Geräten. **Niemand im offenen Internet
sieht dein Tool** — keine Angriffsfläche, keine geklauten API-Keys.

### Einmalig einrichten

1. **Account:** https://tailscale.com → kostenlos registrieren (Google/GitHub-Login geht).
2. **Auf dem PC (Windows):** Tailscale installieren von https://tailscale.com/download
   → installieren → einloggen. Der PC bekommt eine feste Tailscale-IP, z.B. `100.x.x.x`.
   (IP findest du per Rechtsklick aufs Tailscale-Tray-Icon → "Copy my IP".)
3. **Auf Handy/Laptop:** Tailscale-App installieren, mit **demselben Account** einloggen.

### Tool starten (auf dem PC)

Option A — direkt auf der Tailscale-IP lauschen (einfachste Variante):

```bat
set BEZY_HOST=0.0.0.0
set BEZY_PORT=7860
.venv\Scripts\python.exe gui.py
```

> `0.0.0.0` heißt "lausche auf allen Netzwerk-Karten". Da dein PC hinter dem
> Router-NAT sitzt, ist er trotzdem **nicht** aus dem offenen Internet erreichbar —
> nur LAN + dein Tailscale-Netz. Das ist gewollt und sicher.

### Zugreifen (von überall)

- Tailscale-App auf dem Handy/Laptop **an**.
- Browser öffnen → `http://100.x.x.x:7860` (die Tailscale-IP deines PCs).
- Fertig. Dein Generator, von überall, nur für dich.

### Noch sauberer (optional): `tailscale serve`

Gibt dir eine echte HTTPS-Adresse im Tailnet, ohne Port-Tippen. Auf dem PC:

```bat
rem Tool wie gewohnt lokal starten (Standard-Bind 127.0.0.1):
set BEZY_PORT=7860
.venv\Scripts\python.exe gui.py

rem In einem zweiten Fenster:
tailscale serve --bg http://localhost:7860
```

Dann erreichst du es unter `https://<dein-pc-name>.<tailnet>.ts.net` — mit gültigem
HTTPS-Zertifikat, nur in deinem Tailnet sichtbar.

---

## Weg 2 — Cloudflare Tunnel (nur wenn du eine FESTE öffentliche URL willst)

Sinnvoll, falls du das Tool später Kunden zeigen willst. Hier **unbedingt Login an**:

```bat
set BEZY_HOST=127.0.0.1
set BEZY_PORT=7860
set BEZY_AUTH=bezy:einSicheresPasswort
.venv\Scripts\python.exe gui.py
```

Tunnel (einmal `cloudflared` installieren von cloudflare.com):

```bat
cloudflared tunnel --url http://localhost:7860
```

Du bekommst eine `https://...trycloudflare.com`-URL. Für eine **feste** Adresse
brauchst du eine eigene Domain + benannten Tunnel (Cloudflare-Doku). Wegen
öffentlicher Erreichbarkeit ist `BEZY_AUTH` hier Pflicht.

---

## Weg 3 — Gradio Share (nur schnelles Testen, NICHT dauerhaft)

Schnellster Weg, aber Link ist 72 h gültig und jeder mit Link kommt rein.
Dafür müsste in `gui.py` `share=True` gesetzt werden — nur für kurze Tests
empfohlen, nicht als Dauerlösung.

---

## Wann doch einen Server mieten?

Erst wenn:
- du es **24/7 ohne deinen PC** brauchst, ODER
- **fremde User** sich registrieren sollen (echte Web-App).

Dann (Reihenfolge nach Preis):
- **CPU-VPS** (Hetzner CPX, ~5-10 €/mo): reicht, weil die KI extern läuft.
  Whisper auf CPU = langsamer, YOLO fällt auf MediaPipe zurück. Gut zum Hosten der App.
- **GPU pay-per-use** (RunPod / Vast.ai, ~0,20-0,40 $/Std): nur zahlen wenn ein
  Video rendert. Ideal sobald Kunden zahlen — kein Leerlauf-Kosten.
- **Dedizierter GPU-Server** (~150-200 €/mo): erst bei echtem, konstantem Volumen.

> Für "nur ich, von überall" ist das alles **unnötig**. Bleib bei Tailscale + deinem PC.

---

## Sicherheits-Hinweise

- `config.json` mit deinen API-Keys **niemals** committen (steht in `.gitignore` — prüfen!).
- Bei öffentlichen Wegen (Cloudflare/Share) **immer** `BEZY_AUTH` setzen.
- Tailscale braucht keinen Login-Schutz, weil das Netz selbst schon privat ist.
