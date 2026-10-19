@echo off
title Compilation Aero Contrôle
color 0B
echo ========================================
echo   Compilation d'Aero Contrôle en .exe
echo ========================================
echo.

:: Vérifie que Python est disponible
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas trouvé dans le PATH.
    echo Installe Python et coche "Add Python to PATH".
    pause
    exit /b 1
)

echo [1/3] Installation / mise a jour des dependances...
python -m pip install --upgrade pip >nul
python -m pip install pillow psutil pystray pyinstaller --quiet
if errorlevel 1 (
    echo [ERREUR] Impossible d'installer les packages.
    pause
    exit /b 1
)
echo       OK

echo.
echo [2/3] Nettoyage des anciens builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist AeroControle.spec del /q AeroControle.spec
echo       OK

echo.
echo [3/3] Compilation en cours (peut prendre 1-2 minutes)...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AeroControle" ^
    --clean ^
    --hidden-import=pystray._win32 ^
    --hidden-import=PIL._tkinter_finder ^
    --collect-all pystray ^
    aero_controle.py

if errorlevel 1 (
    echo.
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Compilation terminee avec succes !
echo ========================================
echo.
echo L'executable se trouve ici :
echo   %cd%\dist\AeroControle.exe
echo.
echo Tu peux le copier ou le lancer directement.
echo.
pause