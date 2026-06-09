# UNATTENDED — PC ferientauglich machen (24/7 Fernbetrieb)

Ziel: Dein RTX-3080-PC läuft als Server, du steuerst alles aus den Ferien
(z.B. Nordmazedonien) per Handy. Friert er ein → per Smart-Steckdose aus der
Ferne neu starten, Tool kommt von selbst wieder hoch.

**Voraussetzungen, die du schon hast:** Tailscale (PC + Handy), `start-remote.bat`.
**Neu dazu:** Smart-Steckdose mit CH-Stecker (z.B. Hombli Smart Swiss Socket),
`start-unattended.bat` (Watchdog).

> ⚠️ **Wichtigste Einzelregel:** Stecke den PC in die Smart-Steckdose, aber
> **NIEMALS den Router** — sonst schaltest du dir aus der Ferne dein eigenes
> Internet ab und kommst an nichts mehr ran. Router immer direkt an die Wand.

---

## Schritt 1 — BIOS: PC startet nach Strom-an von selbst (KRITISCH)

Ohne das bringt die Steckdose nichts — nach „Strom an" bliebe der PC sonst aus.

1. PC neu starten, beim Hochfahren `Entf` / `F2` / `F10` drücken (Hersteller-abhängig)
   → BIOS/UEFI öffnet sich.
2. Einstellung suchen (heißt je nach Board unterschiedlich):
   - **„Restore on AC Power Loss"** → auf **„Power On"** / **„On"** / **„Last State"**
   - oder **„AC Back"** / **„Power On After Power Failure"** → **Enabled**
   - Meist unter *Advanced* → *Power Management* / *APM*.
3. Speichern (`F10`) und neu starten.

**Test:** PC herunterfahren, kurz Strom an der Steckdose ziehen und wieder
einstecken. Wenn der PC **von selbst** angeht → passt. ✅

---

## Schritt 2 — Schlafmodus & Bildschirm-Aus deaktivieren

Häufigste „Freeze"-Ursache ist in Wahrheit: PC geht schlafen und ist nicht mehr
erreichbar. In PowerShell (als Admin) ausführen:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /hibernate off
```

(`0` = nie. Der PC bleibt dauerhaft wach und erreichbar.)

---

## Schritt 3 — Auto-Login (PC bootet direkt in den Desktop)

Nach einem Neustart muss Windows ohne Passwort-Eingabe bis zum Desktop kommen,
sonst startet das Tool nicht.

1. `Win + R` → `netplwiz` → Enter
2. Deinen Benutzer markieren → Häkchen **„Benutzer müssen Benutzernamen und
   Kennwort eingeben"** **entfernen** → Übernehmen → Passwort 2x eingeben.

> Fehlt das Häkchen (Windows 11): *Einstellungen → Konten → Anmeldeoptionen*
> → **„Für mehr Sicherheit … Windows Hello-Anmeldung … erforderlich"** auf
> **Aus** stellen. Dann erscheint das Häkchen in `netplwiz`.

---

## Schritt 4 — Tool automatisch beim Hochfahren starten

`start-unattended.bat` (der Watchdog) in den Autostart-Ordner legen — er startet
das Tool und re-startet es automatisch, falls es abstürzt.

1. `Win + R` → `shell:startup` → Enter (öffnet den Autostart-Ordner)
2. **Verknüpfung** von `start-unattended.bat` hineinlegen:
   - Rechtsklick auf `start-unattended.bat` → *Kopieren*
   - im Autostart-Ordner → Rechtsklick → *Verknüpfung einfügen*

**Test:** PC neu starten → nach dem Login muss sich ein Fenster öffnen mit
`Starte GUI auf http://0.0.0.0:7860`. ✅

---

## Schritt 5 — Windows-Updates während der Ferien zähmen

Verhindert, dass Windows mitten in der Nacht neu startet und evtl. hängen bleibt.

- *Einstellungen → Windows Update → Updates aussetzen* → für die Dauer deiner
  Reise pausieren (max. 5 Wochen).
- Optional *Erweiterte Optionen → Nutzungszeit* auf einen weiten Bereich setzen.

---

## Schritt 6 — Smart-Steckdose einrichten (Hombli)

1. **Hombli-App** installieren (iOS/Android), Konto anlegen.
2. Steckdose in die Wand, PC-Kabel in die Steckdose.
3. In der App hinzufügen — **Handy muss im 2.4-GHz-WLAN** sein beim Einrichten.
4. Steckdose benennen, z.B. „Render-PC".
5. **WLAN am Router muss dauerhaft an bleiben**, sonst ist die Steckdose aus der
   Ferne nicht erreichbar (auch wenn dein PC per LAN-Kabel hängt).

---

## So nutzt du es aus den Ferien

**Normalfall (PC läuft):**
- Handy: Tailscale **an** → Browser → `http://100.118.9.106:7860` → Tool steuern.

**PC eingefroren / nicht erreichbar:**
1. Hombli-App → Steckdose **AUS**
2. ~10 Sekunden warten
3. Steckdose **AN**
4. PC bootet → Auto-Login → Watchdog startet das Tool → nach 1-2 Min wieder per
   Tailscale erreichbar.

---

## Vor der Abreise: 1x echten Test machen

Mach das **bevor** du wegfährst, nicht erst in den Ferien:

- [ ] BIOS-Power-On getestet (Schritt 1)
- [ ] PC neu gestartet → Tool startet automatisch (Schritt 4)
- [ ] Vom **Handy mit mobilen Daten** (WLAN am Handy AUS!) per Tailscale aufs
      Tool zugegriffen — beweist, dass es übers Internet geht, nicht nur im Heim-WLAN.
- [ ] Mit der Hombli-App einen Power-Cycle gemacht und geprüft, dass der PC
      von selbst hochfährt und das Tool wiederkommt.

Wenn alle 4 Haken sitzen, bist du ferientauglich. 🌍

---

## Grenzen (ehrlich)

- Fällt dein **Heim-Internet/Router** komplett aus, erreichst du weder Steckdose
  noch PC — dagegen hilft kein Setup aus der Ferne.
- Ein Hardware-Defekt (Netzteil, Lüfter) lässt sich aus der Ferne nicht beheben.
- Für garantierte 24/7-Verfügbarkeit bei langer Abwesenheit wäre irgendwann ein
  Cloud-GPU-Dienst (pay-per-use) robuster — aber für den Normalfall reicht
  dein PC + Steckdose locker.
