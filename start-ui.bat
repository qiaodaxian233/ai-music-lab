@echo off
chcp 65001 >nul
title AI Music Lab - ACE-Step 主 UI (端口 7860)
echo.
echo ========================================
echo   AI Music Lab - 主 UI (ACE-Step 1.5)
echo ========================================
echo.

if not exist "ACE-Step-1.5\start_gradio_ui.bat" (
    echo [错误] 找不到 ACE-Step-1.5\start_gradio_ui.bat
    echo.
    echo 请先在 cmd 里跑:
    echo   git clone https://github.com/ace-step/ACE-Step-1.5.git
    echo.
    pause
    exit /b 1
)

echo 调用 ACE-Step 1.5 官方启动器...
echo 启动地址: http://localhost:7860
echo 关闭窗口即停止服务
echo.

cd ACE-Step-1.5
start_gradio_ui.bat
