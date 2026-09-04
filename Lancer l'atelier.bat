@echo off
rem Raccourci de lancement de l'interface. A epingler a la barre des taches.
cd /d "%~dp0"
start "" pythonw -m ripcore.ui
if errorlevel 1 (
  echo.
  echo Impossible de demarrer. Verifiez que Python est installe :
  echo     python --version
  echo.
  pause
)
