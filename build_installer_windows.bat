@echo off
setlocal
cd /d "%~dp0"

call build_windows.bat
if errorlevel 1 exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 nao foi encontrado.
    echo Instale o Inno Setup e execute este arquivo novamente.
    pause
    exit /b 1
)

if not exist release mkdir release

"%ISCC%" "installer\Padroniza.iss"
if errorlevel 1 (
    echo.
    echo A criacao do instalador falhou.
    pause
    exit /b 1
)

echo.
echo Instalador criado na pasta:
echo %CD%\release
echo.
start "" "%CD%\release"
exit /b 0
