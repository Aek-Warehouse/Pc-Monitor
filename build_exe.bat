@echo off
setlocal

cd /d "%~dp0"

echo Creating clean build environment...
if exist app\.build_venv rmdir /s /q app\.build_venv
py -3 -m venv app\.build_venv
if errorlevel 1 goto build_failed

set "PYTHON_EXE=%~dp0app\.build_venv\Scripts\python.exe"

echo Installing build requirements...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto build_failed

"%PYTHON_EXE%" -m pip install -r app\requirements.txt
if errorlevel 1 goto build_failed

echo.
echo Building PCMonitor.exe...
"%PYTHON_EXE%" app\build.py
if errorlevel 1 goto build_failed

echo.
echo Build complete.
echo The packaged self-test passed.
echo Your publishable file is:
echo %~dp0app\dist\PCMonitor.exe
pause
exit /b 0

:build_failed
echo.
echo Build failed. Read the error above, then try again.
pause
exit /b 1
