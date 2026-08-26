@echo off
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo   Compilando Padroniza para Windows
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

echo Limpando compilacoes anteriores...
if exist build rmdir /s /q build
if exist "dist\Padroniza.exe" del /q "dist\Padroniza.exe"
if exist Padroniza.spec del /q Padroniza.spec

echo Gerando aplicativo...
if exist "assets\padroniza.ico" (
    ".venv\Scripts\python.exe" -m PyInstaller ^
        --noconfirm ^
        --clean ^
        --windowed ^
        --onefile ^
        --name Padroniza ^
        --icon "assets\padroniza.ico" ^
        --add-data "app/ui/styles:app/ui/styles" ^
        --add-data "templates:templates" ^
        --add-data "examples:examples" ^
        --add-data "assets:assets" ^
        --add-data "docs:docs" ^
        main.py
) else (
    ".venv\Scripts\python.exe" -m PyInstaller ^
        --noconfirm ^
        --clean ^
        --windowed ^
        --onefile ^
        --name Padroniza ^
        --add-data "app/ui/styles:app/ui/styles" ^
        --add-data "templates:templates" ^
        --add-data "examples:examples" ^
        --add-data "assets:assets" ^
        --add-data "docs:docs" ^
        main.py
)
if errorlevel 1 goto :error

echo.
echo Compilacao concluida.
echo Executavel:
echo %CD%\dist\Padroniza.exe
echo.
start "" "%CD%\dist"
exit /b 0

:error
echo.
echo A compilacao falhou. Revise as mensagens acima.
pause
exit /b 1
