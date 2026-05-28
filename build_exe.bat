@echo off
REM ============================================================
REM  Bezys Shorts Generator - EXE Builder
REM  Doppelklick = baut BezysShortsGenerator.exe in .\dist\
REM  Muss AUF Windows laufen (eine Windows-.exe kann nur auf
REM  Windows erzeugt werden). Nutzt deine bestehende .venv.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Bezys Shorts Generator - EXE Build ===
echo.

REM venv-Python finden (sonst System-Python)
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/3] PyInstaller sicherstellen...
"%PY%" -m pip install --quiet --upgrade pyinstaller || goto :err

echo [2/3] Baue EXE (das dauert ein paar Minuten)...
"%PY%" -m PyInstaller --noconfirm bezys.spec || goto :err

echo.
echo [3/3] FERTIG.
echo Deine App: dist\BezysShortsGenerator\BezysShortsGenerator.exe
echo (Den ganzen Ordner "dist\BezysShortsGenerator" kannst du verschieben/kopieren.)
echo Wichtig: config.json + ffmpeg muessen wie gewohnt erreichbar sein.
echo.
pause
exit /b 0

:err
echo.
echo *** BUILD FEHLGESCHLAGEN - siehe Fehler oben. ***
pause
exit /b 1
