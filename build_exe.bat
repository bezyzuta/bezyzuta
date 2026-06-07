@echo off
REM ============================================================
REM  Bezys Shorts Generator - EXE Builder
REM  Doppelklick = baut BezysShortsGenerator.exe in .\dist\
REM  Muss AUF Windows laufen. Die .exe ist ein schlanker Starter,
REM  der deine .venv + gui.py findet und startet.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Bezys Shorts Generator - EXE Build ===
echo.

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/3] PyInstaller sicherstellen...
"%PY%" -m pip install --quiet --upgrade pyinstaller || goto :err

echo [2/3] Baue EXE (eine Minute, klein da nur Starter)...
"%PY%" -m PyInstaller --noconfirm bezys.spec || goto :err

echo.
echo [3/3] FERTIG.
echo Deine App: dist\BezysShortsGenerator.exe
echo.
echo Kopier die .exe in DIESEN Projektordner (neben gui.py / config.json)
echo und mach dir davon eine Desktop-Verknuepfung. Doppelklick startet die GUI.
echo.

REM Bequem: gleich neben gui.py legen, damit Doppelklick sofort geht.
if exist "dist\BezysShortsGenerator.exe" copy /Y "dist\BezysShortsGenerator.exe" "BezysShortsGenerator.exe" >nul && echo (Kopie liegt jetzt auch direkt hier: BezysShortsGenerator.exe)
echo.
pause
exit /b 0

:err
echo.
echo *** BUILD FEHLGESCHLAGEN - siehe Fehler oben. ***
pause
exit /b 1
