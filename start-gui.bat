@echo off
title Roblox Shorts Generator
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo FEHLER: virtuelle Umgebung nicht gefunden in .venv
    echo Stelle sicher dass diese BAT-Datei im Projektordner liegt
    echo (neben pipeline.py und gui.py^).
    pause
    exit /b 1
)

if not exist "gui.py" (
    echo FEHLER: gui.py nicht gefunden in %CD%
    pause
    exit /b 1
)

echo ===========================================
echo  Roblox Shorts Generator
echo ===========================================
echo Browser oeffnet sich gleich automatisch.
echo Zum Beenden: dieses Fenster schliessen oder Strg+C.
echo.
.venv\Scripts\python.exe gui.py
echo.
echo === GUI beendet ===
pause
