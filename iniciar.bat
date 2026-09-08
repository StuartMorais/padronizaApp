@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_python
echo Criando ambiente do Office Tools...
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto check_python
:use_python
python -m venv .venv
if errorlevel 1 goto failed
:check_python
".venv\Scripts\python.exe" -c "import sys, struct; print('Python ' + sys.version.split()[0] + ' - ' + str(struct.calcsize('P') * 8) + ' bits'); sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 goto unsupported_python
:check_dependencies
".venv\Scripts\python.exe" -c "from importlib.metadata import version; assert version('PySide6-Essentials') == '6.10.3'; assert version('shiboken6') == '6.10.3'; from PySide6.QtWidgets import QApplication; from PySide6.QtSvg import QSvgRenderer; import docx, reportlab, fitz, PIL, win32com.client" >nul 2>nul
if not errorlevel 1 goto launch
echo Instalando dependencias. A primeira execucao precisa de internet...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto failed
popd
exit /b 0
:unsupported_python
echo.
echo Este pacote requer Python 3.10 a 3.14 de 64 bits.
echo Consulte a secao de ambiente virtual no README.md.
pause
popd
exit /b 1
:failed
echo.
echo Nao foi possivel iniciar o Office Tools.
echo Consulte a mensagem acima e o README.md para corrigir a instalacao.
pause
popd
exit /b 1
