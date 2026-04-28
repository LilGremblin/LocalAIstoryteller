@echo off
title KoboldCPP Setup
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║      KoboldCPP Setup for 12GB       ║
echo  ╚══════════════════════════════════════╝
echo.

REM Create koboldcpp directory
if not exist "koboldcpp" mkdir koboldcpp
cd koboldcpp

REM Download KoboldCPP
if not exist "koboldcpp.exe" (
    echo [*] Downloading KoboldCPP...
    echo     This is the recommended LLM backend for AI Story Engine.
    echo.
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/LostRuins/koboldcpp/releases/latest/download/koboldcpp.exe' -OutFile 'koboldcpp.exe'"
    if %errorlevel% neq 0 (
        echo [ERROR] Download failed. Please download manually from:
        echo         https://github.com/LostRuins/koboldcpp/releases
        pause
        exit /b 1
    )
    echo [OK] KoboldCPP downloaded.
) else (
    echo [OK] KoboldCPP already exists.
)

echo.
echo ═══════════════════════════════════════════════════════════════
echo  NEXT STEPS:
echo ═══════════════════════════════════════════════════════════════
echo.
echo  1. Download a model (GGUF format) for your 12GB VRAM:
echo.
echo     RECOMMENDED MODELS:
echo     ─────────────────────────────────────────────────────────
echo     Mistral 7B Instruct v0.3 (Q4_K_M) - ~4.4GB
echo       https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF
echo.
echo     Gemma 2 9B Instruct (Q4_K_M) - ~5.8GB  
echo       https://huggingface.co/bartowski/gemma-2-9b-it-GGUF
echo.
echo     Mistral Small 3.1 24B (IQ3_M) - ~10.5GB [BEST QUALITY]
echo       https://huggingface.co/bartowski/Mistral-Small-3.1-24B-Instruct-2503-GGUF
echo     ─────────────────────────────────────────────────────────
echo.
echo  2. Launch KoboldCPP:
echo       koboldcpp\koboldcpp.exe
echo.
echo  3. In the KoboldCPP GUI:
echo       - Click "Browse" and select your .gguf model file
echo       - Set GPU Layers: 99 (offload everything to GPU)
echo       - Set Context Size: 8192 (or higher if model supports)
echo       - Click "Launch"
echo.
echo  4. Then run "run.bat" to start AI Story Engine!
echo.
echo ═══════════════════════════════════════════════════════════════
echo.
pause
