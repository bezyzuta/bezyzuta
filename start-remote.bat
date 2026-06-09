@echo off
title Bezys Shorts Generator (Remote / Tailscale)
cd /d "%~dp0"

if not exist "gui.py" (
    echo FEHLER: gui.py nicht gefunden in %CD%
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo FEHLER: .venv nicht gefunden. Bitte zuerst einmal start-gui.bat starten.
    pause
    exit /b 1
)

rem --- Remote-Modus: auf allen Netzwerk-Karten lauschen (inkl. Tailscale) ---
set BEZY_HOST=0.0.0.0
set BEZY_PORT=7860

rem Optional: Login-Schutz aktivieren (z.B. fuer Cloudflare/oeffentlich).
rem Einfach die naechste Zeile entkommentieren und Passwort setzen:
rem set BEZY_AUTH=bezy:meinSicheresPasswort

echo ===========================================
echo  Bezys Shorts Generator - REMOTE-MODUS
echo ===========================================
echo.
echo Zugriff vom Handy/Laptop (Tailscale muss AN sein):
echo.
echo     http://[deine-Tailscale-IP]:%BEZY_PORT%
echo.
echo Deine Tailscale-IP findest du per Rechtsklick aufs
echo Tailscale-Tray-Icon -^> "Copy my IP".
echo.
echo Zum Beenden: dieses Fenster schliessen oder Strg+C.
echo ===========================================
echo.
.venv\Scripts\python.exe gui.py
echo.
echo === GUI beendet ===
pause
