@echo off
rem Lance un petit serveur local puis ouvre lhologramme dans le navigateur.
cd /d "%~dp0"
start "" "http://localhost:8765/"
python -m http.server 8765 2>nul || py -m http.server 8765
