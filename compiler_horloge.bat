@echo off
chcp 65001 >nul
title Compilation de Aero Horloge
cd /d "%~dp0"

echo ============================================
echo   Creation de AeroHorloge.exe
echo ============================================
echo.

set PY=
where py >nul 2>nul && set PY=py
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo [ERREUR] Python est introuvable.
    echo Installe-le depuis https://www.python.org/downloads/
    echo et coche "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

echo [1/3] Installation des modules necessaires...
%PY% -m pip install --upgrade pip pillow pystray pyinstaller
if errorlevel 1 (
    echo [ERREUR] Installation des modules impossible.
    pause
    exit /b 1
)

echo.
echo [2/3] Compilation en cours (1 a 2 minutes)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name AeroHorloge ^
    --hidden-import pystray._win32 ^
    aero_horloge.py
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)

echo.
echo [3/3] Nettoyage...
if exist build rmdir /s /q build
if exist AeroHorloge.spec del /q AeroHorloge.spec

echo.
echo ============================================
echo   Termine !
echo   Ton programme est ici :
echo   %~dp0dist\AeroHorloge.exe
echo ============================================
echo.
explorer "%~dp0dist"
pause
