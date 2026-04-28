@echo off
title AI Story Engine
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║        AI STORY ENGINE v1.0          ║
echo  ╚══════════════════════════════════════╝
echo.

REM ─── Configuration ────────────────────────────────────────────────
set "KOBOLD_EXE=%~dp0koboldcpp\koboldcpp.exe"
set "MODEL_DIR=%~dp0models"
set "KOBOLD_PORT=5001"
set "CONTEXT_SIZE=8192"
set "GPU_LAYERS=999"

REM ─── Find the best model ──────────────────────────────────────────
set "MODEL_FILE="

REM Priority 1: Magnum v4 (best creative writing model)
for %%f in ("%MODEL_DIR%\magnum*.gguf") do set "MODEL_FILE=%%f"

REM Priority 2: Any other gguf model
if "%MODEL_FILE%"=="" (
    for %%f in ("%MODEL_DIR%\*.gguf") do set "MODEL_FILE=%%f"
)

REM ─── Check Python ─────────────────────────────────────────────────
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM ─── Create venv if needed ────────────────────────────────────────
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
)

REM ─── Activate venv ────────────────────────────────────────────────
call venv\Scripts\activate.bat

REM ─── Install deps ─────────────────────────────────────────────────
echo [*] Checking dependencies...
pip install -r requirements.txt -q 2>nul

REM ─── Launch KoboldCPP ─────────────────────────────────────────────
if not exist "%KOBOLD_EXE%" (
    echo [!] KoboldCPP not found. Run setup_koboldcpp.bat first.
    echo [*] Starting without LLM backend...
    goto :start_server
)

if "%MODEL_FILE%"=="" (
    echo [!] No model found in %MODEL_DIR%
    echo [!] Download a .gguf model into the models\ folder.
    echo [*] Starting without LLM backend...
    goto :start_server
)

echo [*] Found model: %MODEL_FILE%
echo [*] Launching KoboldCPP on port %KOBOLD_PORT%...
echo     Context: %CONTEXT_SIZE% tokens ^| GPU Layers: %GPU_LAYERS%
echo.

REM Check if KoboldCPP is already running on that port
netstat -ano 2>nul | findstr ":%KOBOLD_PORT% " | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [OK] KoboldCPP already running on port %KOBOLD_PORT%
) else (
    start "KoboldCPP" "%KOBOLD_EXE%" --model "%MODEL_FILE%" --port %KOBOLD_PORT% --contextsize %CONTEXT_SIZE% --gpulayers %GPU_LAYERS% --skiplauncher --smartcontext
    echo [OK] KoboldCPP starting in background...
    REM Wait for it to load
    echo [*] Waiting for model to load...
    timeout /t 5 /nobreak >nul
)

:start_server
echo.
echo [*] Starting AI Story Engine at http://localhost:8000
echo.

REM Wait a moment then open browser
start "" "http://localhost:8000"

python -m uvicorn src.server:app --host 0.0.0.0 --port 8000

pause
