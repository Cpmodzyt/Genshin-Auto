@echo off
setlocal EnableDelayedExpansion
pushd "%~dp0"
title Genshin Auto

:: ============================================
:: Auto-elevate to Administrator
:: ============================================
:: Genshin can ignore synthetic keys sent by a lower-privilege process.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

color 0A
echo ============================================
echo   Genshin Auto - Setup ^& Launcher
echo ============================================
echo [OK] Running as Administrator
echo.

:: ============================================
:: Python check (3.11+)
:: ============================================
where python >nul 2>&1
if errorlevel 1 goto :no_python

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set "PY_VERSION=%%i"
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] %PY_VERSION% detected, but Python 3.11 or newer is required.
    echo         Download it from https://www.python.org/downloads/
    goto :fail
)
echo [OK] %PY_VERSION%
echo.

:: ============================================
:: Virtual environment: create only if missing
:: ============================================
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    color 0E
    echo [..] First run: creating virtual environment...
    where uv >nul 2>&1
    if !errorlevel! equ 0 (
        uv sync
        if errorlevel 1 goto :fail
    ) else (
        python -m venv .venv
        if errorlevel 1 goto :fail
        "%PY%" -m pip install --upgrade pip >nul 2>&1
        "%PY%" -m pip install -r requirements.txt
        if errorlevel 1 goto :fail
    )
)

if not exist "%PY%" (
    color 0C
    echo [ERROR] Could not create .venv\Scripts\python.exe
    goto :fail
)
echo [OK] Virtual environment ready
echo.

:: ============================================
:: Dependency check: install only if missing
:: ============================================
"%PY%" -c "import pyautogui, pyscreeze, dotenv, win32api, PIL" >nul 2>&1
if errorlevel 1 (
    color 0E
    echo [..] Dependencies missing or incomplete. Installing...
    "%PY%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo [..] pip is missing from this environment - bootstrapping...
        "%PY%" -m ensurepip --upgrade >nul 2>&1
    )
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
)

:: Verify a second time so a failed install cannot slip through.
"%PY%" -c "import pyautogui, pyscreeze, dotenv, win32api, PIL" >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Dependency verification failed.
    echo         Try: "%PY%" -m pip install -r requirements.txt
    goto :fail
)
echo [OK] Dependencies verified
echo.

:: ============================================
:: Configuration sanity check
:: ============================================
"%PY%" -c "import autoskip_dialogue as a; a.load_config()" >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Configuration sanity check failed.
    echo         Run:  run.bat --probe
    goto :fail
)
echo [OK] Configuration ready
echo.

:: ============================================
:: Run
:: ============================================
color 0B
echo ============================================
echo   Starting Genshin Auto...
echo ============================================
echo   Tip: you can pass options through run.bat
echo        run.bat --probe
echo        run.bat --hotkey-test
echo        run.bat --debug
echo ============================================
echo.
color 0F

"%PY%" autoskip_dialogue.py %*
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%" equ "0" (
    color 0A
    echo [OK] Finished.
    goto :done
)

color 0C
echo [ERROR] Script exited with code %EXIT_CODE%.
echo.
echo Run the diagnostics to find out why:
echo    run.bat --probe
echo    run.bat --hotkey-test
echo.
set /p "RETRY=Retry? (Y/N): "
if /i "%RETRY%"=="Y" (
    "%PY%" autoskip_dialogue.py %*
)
goto :done

:no_python
color 0C
echo [ERROR] Python was not found in PATH.
echo.
echo Install Python 3.11+ from https://www.python.org/downloads/
echo and tick "Add Python to PATH" during setup.
goto :fail

:fail
color 0C
echo.
echo [ERROR] Setup failed. Read the messages above.
echo.

:done
echo.
pause
popd
