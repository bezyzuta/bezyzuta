@echo off
REM ============================================================================
REM  Autopilot starten (Doppelklick) — rendert die Queue autopilot.jobs.json
REM  und laedt optional zu YouTube hoch. KEINE Claude-Tokens.
REM  Nutzt dieselbe .venv wie start-gui.bat.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [FEHLER] .venv\Scripts\python.exe nicht gefunden in %CD%
  echo Starte dieses .bat aus dem Projektordner (dort wo gui.py liegt^).
  pause
  exit /b 1
)

if not exist "autopilot.jobs.json" (
  echo [HINWEIS] autopilot.jobs.json fehlt.
  echo Kopiere autopilot.example.json nach autopilot.jobs.json und trage deine Jobs ein.
  pause
  exit /b 1
)

echo ============================================================
echo  Autopilot laeuft... (Fenster offen lassen)
echo  Abbrechen: dieses Fenster schliessen oder Strg+C
echo ============================================================
"%PY%" autopilot.py autopilot.jobs.json %*

echo.
echo ============================================================
echo  Autopilot fertig. Siehe autopilot_state.json fuer Details.
echo ============================================================
pause
endlocal
