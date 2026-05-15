@echo off
chcp 65001 >nul
title AI Music Lab - 总控台 (端口 7862)
echo.
echo ========================================
echo   AI Music Lab - 总控台
echo ========================================
echo.
echo 启停 / 监控 3 个服务 + 系统状态
echo 启动地址: http://localhost:7862
echo 关闭窗口即停止总控台 (各服务还会继续跑)
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [错误] 找不到 .venv
    echo.
    echo 这个工具需要 ai-music-lab 的 venv. 修复办法:
    echo   1. 删了重建: rmdir /s /q .venv  然后 python -m venv .venv
    echo   2. 激活: .venv\Scripts\activate.bat
    echo   3. 装依赖: pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python -c "import gradio" 2>nul
if errorlevel 1 (
    echo [错误] gradio 未装. 先跑:
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

python -c "import psutil" 2>nul
if errorlevel 1 (
    echo [警告] psutil 未装,进程管理会用退化模式 (不稳)
    echo   pip install psutil
    echo.
)

python scripts\lab-manager.py
pause
