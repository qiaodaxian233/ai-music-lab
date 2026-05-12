@echo off
chcp 65001 >nul
title AI Music Lab - 统一控制台 (端口 7861)
echo.
echo ========================================
echo   AI Music Lab - 统一控制台
echo ========================================
echo.
echo 4 个 Tab: 历史 / LoRA / DAW 导出 / 后处理
echo 启动地址: http://localhost:7861
echo 关闭窗口即停止服务
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
    echo   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
)

python scripts\unified-ui.py
pause
