@echo off
chcp 65001 >nul
title AI Music Lab - Manager (port 7862)
echo.
echo ========================================
echo   AI Music Lab - Manager
echo ========================================
echo.
echo Start / stop / monitor 3 services
echo URL: http://localhost:7862
echo Close this window to stop the manager (the services keep running)
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv not found
    echo.
    echo This tool needs ai-music-lab's venv. Fix:
    echo   1. Recreate:  rmdir /s /q .venv  then  python -m venv .venv
    echo   2. Activate:  .venv\Scripts\activate.bat
    echo   3. Install:   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python -c "import gradio" 2>nul
if errorlevel 1 (
    echo [ERROR] gradio not installed. Run:
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

python -c "import psutil" 2>nul
if errorlevel 1 (
    echo [WARN] psutil not installed, falling back to degraded process mgmt
    echo   pip install psutil
    echo.
)

python scripts\lab-manager.py
pause
