@echo off
rem Installation et mise a jour du RIP. A double-cliquer.
rem Pas d'accents dans ce fichier : la console Windows ne les affiche pas.
setlocal
title Installation du RIP
pushd "%~dp0"

echo.
echo   ============================================
echo    RIP Symp's - installation / mise a jour
echo   ============================================
echo.

rem -- 1. Trouver Python -------------------------------------------------
rem "py" est le lanceur officiel Windows. On l'essaie en premier : il evite
rem le raccourci Microsoft Store, qui detourne "python" vers le magasin et
rem donne l'impression que Python est installe alors qu'il ne l'est pas.
set PY=
py -3 --version >nul 2>nul
if %errorlevel%==0 set PY=py -3
if defined PY goto python_trouve
python --version >nul 2>nul
if %errorlevel%==0 set PY=python
:python_trouve
if not defined PY goto pas_de_python

echo   Python detecte :
%PY% --version
echo.

rem -- 2. Recuperer la derniere version ----------------------------------
where git >nul 2>nul
if not %errorlevel%==0 goto sans_git
echo   Recuperation de la derniere version...
git pull --ff-only
echo.
:sans_git

rem -- 3. Installer -------------------------------------------------------
echo   Installation des composants (numpy, Pillow, tifffile)...
echo   La premiere fois, comptez deux a trois minutes.
echo.
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install -e ".[images]"
if errorlevel 1 goto echec

rem -- 4. Verifier que ca marche vraiment ---------------------------------
echo.
echo   Verification...
%PY% -c "import ripcore, numpy, PIL, tifffile; print('   Version', ripcore.__version__, '- tout est en place.')"
if errorlevel 1 goto echec

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 echo   ATTENTION : Tkinter manque, l'interface ne demarrera pas. Reinstallez Python depuis python.org.

echo.
echo   ============================================
echo    Termine. Lancez "Lancer l'atelier.bat".
echo   ============================================
echo.
popd
pause
exit /b 0

:pas_de_python
echo   Python n'est pas installe, ou pas accessible.
echo.
echo   1. Allez sur https://www.python.org/downloads/
echo   2. Telechargez Python 3.11 ou plus recent
echo   3. IMPORTANT : cochez "Add python.exe to PATH" sur le premier ecran
echo   4. Relancez ce fichier
echo.
echo   N'installez pas Python depuis le Microsoft Store : il manque des
echo   composants necessaires a l'interface.
echo.
popd
pause
exit /b 1

:echec
echo.
echo   L'installation a echoue. Le detail est juste au-dessus.
echo   Recopiez les dernieres lignes rouges pour qu'on regarde ensemble.
echo.
popd
pause
exit /b 1
