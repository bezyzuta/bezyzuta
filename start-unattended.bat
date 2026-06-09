@echo off
title Bezys Shorts Generator (Unattended / Watchdog)
cd /d "%~dp0"

rem ============================================================
rem  FERIEN-/UNBEAUFSICHTIGT-MODUS
rem  Startet die GUI im Remote-Modus und startet sie automatisch
rem  NEU, falls sie abstuerzt. Fuer den Dauerbetrieb, wenn du
rem  nicht am PC bist. Siehe UNATTENDED.md fuer das ganze Setup.
rem  Zum Beenden: dieses Fenster schliessen oder 2x Strg+C.
rem ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo FEHLER: .venv nicht gefunden. Zuerst einmal start-gui.bat starten.
    pause
    exit /b 1
)

rem --- Remote-Modus: auf allen Netzwerk-Karten lauschen (inkl. Tailscale) ---
set BEZY_HOST=0.0.0.0
set BEZY_PORT=7860

rem Optional: Login-Schutz (nur noetig fuer Cloudflare/oeffentlich, NICHT fuer
rem Tailscale). Naechste Zeile entkommentieren + Passwort setzen:
rem set BEZY_AUTH=bezy:meinSicheresPasswort

echo ============================================================
echo  Bezys Shorts Generator - UNBEAUFSICHTIGT (Watchdog)
echo  Zugriff (Tailscale an): http://[deine-Tailscale-IP]:%BEZY_PORT%
echo  Stuerzt die App ab, startet sie nach 10s automatisch neu.
echo ============================================================

:loop
echo.
echo [%date% %time%] Starte GUI...
.venv\Scripts\python.exe gui.py
echo [%date% %time%] GUI beendet oder abgestuerzt.
echo Neustart in 10 Sekunden... (zum endgueltigen Beenden: Strg+C)
timeout /t 10 /nobreak >nul
goto loop
