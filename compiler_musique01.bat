```bat
@echo off
chcp 65001 >nul
title Compilateur Aero Musique
color 0B
setlocal

echo.
echo  ==========================================
echo       AERO MUSIQUE - COMPILATEUR EXE
echo  ==========================================
echo.

cd /d "%~dp0"

set "PYFILE="
if exist "AeroMusique.py" set "PYFILE=AeroMusique.py"
if not defined PYFILE (
    for %%F in (*.py) do (
        if not defined PYFILE set "PYFILE=%%F"
    )
)

if not defined PYFILE (
    echo [ERREUR] Aucun fichier Python trouve.
    echo Place ce BAT a cote du fichier .py.
    pause
    exit /b 1
)

echo [INFO] Fichier detecte : %PYFILE%
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python est introuvable.
    echo Installe Python 3.12 depuis :
    echo https://www.python.org/downloads/
    echo Coche Add Python to PATH pendant l'installation.
    pause
    exit /b 1
)

echo [1/4] Verification de Python...
py -3 -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation de pip...
    py -3 -m ensurepip --upgrade
)

echo.
echo [2/4] Installation des dependances...
py -3 -m pip install --upgrade pyinstaller pillow pystray

if errorlevel 1 (
    echo [ERREUR] Installation des dependances echouee.
    pause
    exit /b 1
)

echo.
echo [3/4] Compilation de Aero Musique...
py -3 -m PyInstaller ^
 --noconfirm ^
 --clean ^
 --onefile ^
 --windowed ^
 --name AeroMusique ^
 --collect-all PIL ^
 --collect-all pystray ^
 "%PYFILE%"

if errorlevel 1 (
    echo.
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)

echo.
echo [4/4] Verification du resultat...

if not exist "dist\AeroMusique.exe" (
    echo [ERREUR] Le fichier EXE est introuvable.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo          COMPILATION REUSSIE !
echo  ==========================================
echo.
echo  Ton application est ici :
echo  %CD%\dist\AeroMusique.exe
echo.
echo  Tu peux copier cet EXE ou le deplacer.
echo  Les parametres seront sauvegardes dans :
echo  %%LOCALAPPDATA%%\AeroMusique
echo.
echo  ATTENTION : teste le programme avant
echo  d'activer le demarrage automatique.
echo.
pause
exit /b 0
```