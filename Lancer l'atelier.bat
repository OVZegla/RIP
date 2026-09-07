@echo off
rem Raccourci de lancement de l'interface. A epingler a la barre des taches.
rem Pas d'accents : la console Windows ne les affiche pas.
setlocal
title RIP Symp's
pushd "%~dp0"

rem On verifie AVANT de lancer. L'interface demarre avec pythonw, qui n'a pas
rem de console : si quelque chose manque, l'utilisateur ne verrait rien du
rem tout - juste un double-clic sans effet. Mieux vaut un message ici.
rem Une branche par cas : "if cmd1 & cmd2" executerait cmd2 dans tous les cas.
py -3 --version >nul 2>nul
if %errorlevel%==0 goto avec_py
python --version >nul 2>nul
if %errorlevel%==0 goto avec_python
goto pas_de_python

:avec_py
set PY=py -3
set PYW=pyw -3
goto python_trouve

:avec_python
set PY=python
set PYW=pythonw

:python_trouve

%PY% -c "import ripcore" >nul 2>nul
if errorlevel 1 goto pas_installe

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto pas_de_tkinter

start "" %PYW% -m ripcore.ui
popd
exit /b 0

:pas_de_python
echo.
echo   Python n'est pas installe sur ce poste.
echo   Double-cliquez sur "Installer ou mettre a jour.bat" : il vous guidera.
echo.
popd
pause
exit /b 1

:pas_installe
echo.
echo   Le RIP n'est pas encore installe sur ce poste.
echo   Double-cliquez sur "Installer ou mettre a jour.bat", puis revenez ici.
echo.
popd
pause
exit /b 1

:pas_de_tkinter
echo.
echo   Tkinter manque : l'interface ne peut pas demarrer.
echo   Reinstallez Python depuis python.org (pas depuis le Microsoft Store)
echo   en cochant "Add python.exe to PATH".
echo.
popd
pause
exit /b 1
