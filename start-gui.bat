@echo off
title Bezys Shorts Generator
cd /d "%~dp0"

if not exist "gui.py" (
    echo FEHLER: gui.py nicht gefunden in %CD%
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo .venv nicht gefunden - erstelle virtuelle Umgebung...
    where python >nul 2>nul
    if errorlevel 1 (
        echo FEHLER: python ist nicht installiert oder nicht im PATH.
        echo Installiere Python von https://www.python.org/downloads/
        echo und aktiviere "Add python.exe to PATH" beim Installieren.
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 (
        echo FEHLER: konnte .venv nicht erstellen.
        pause
        exit /b 1
    )
    echo Installiere Abhaengigkeiten - das dauert 1-2 Minuten...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo FEHLER: pip install fehlgeschlagen.
        pause
        exit /b 1
    )
    echo Setup fertig.
    echo.
)

REM --- Auto-Update: neueste Aenderungen von GitHub holen ---
REM Blockiert den Start NIE: bei lokalen Aenderungen / keinem Fast-Forward
REM wird einfach uebersprungen und die GUI startet trotzdem.
where git >nul 2>nul
if not errorlevel 1 (
    if exist ".git" (
        echo Suche nach Updates...
        git pull --ff-only
        if errorlevel 1 (
            echo.
            echo Hinweis: Auto-Update uebersprungen ^(lokale Aenderungen oder kein Fast-Forward^).
            echo Bei Bedarf einmalig manuell:  git stash ^&^& git pull
            echo.
        ) else (
            echo Auf dem neuesten Stand.
        )
        echo.
    )
)

REM --- Deno: JS-Runtime fuer yt-dlp (YouTube braucht den Challenge-Solver, sonst 403) ---
REM winget legt einen stabilen Shim unter %LOCALAPPDATA%\Microsoft\WinGet\Links an;
REM den haengen wir an PATH, damit die GUI im selben Fenster deno findet.
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
where deno >nul 2>nul
if errorlevel 1 (
    echo Deno nicht gefunden - wird fuer YouTube-Downloads installiert...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo HINWEIS: winget fehlt. Installiere Deno manuell von https://deno.land
        echo          sonst koennen YouTube-Videos evtl. nicht geladen werden.
    ) else (
        winget install DenoLand.Deno --accept-source-agreements --accept-package-agreements --silent
        set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
        echo.
    )
)

echo ===========================================
echo  Bezys Shorts Generator
echo ===========================================
echo Browser oeffnet sich gleich automatisch.
echo Zum Beenden: dieses Fenster schliessen oder Strg+C.
echo.
.venv\Scripts\python.exe gui.py
echo.
echo === GUI beendet ===
pause
