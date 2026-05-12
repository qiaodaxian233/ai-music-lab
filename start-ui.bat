@echo off
chcp 65001 >nul
title AI Music Lab - ACE-Step 主 UI (端口 7860)
echo.
echo ========================================
echo   AI Music Lab - 主 UI
echo ========================================
echo.
echo 启动地址: http://localhost:7860
echo 关闭窗口即停止服务
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [错误] 找不到 .venv,先在 Git Bash 跑: bash setup.sh
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

if not exist "ACE-Step-1.5\app.py" (
    echo [错误] 找不到 ACE-Step-1.5,先在 Git Bash 跑: bash setup.sh
    pause
    exit /b 1
)

cd ACE-Step-1.5

REM 12GB VRAM 优化参数:
REM   --bf16             用 bfloat16 省一半显存
REM   --torch_compile    编译加速 (首次启动多花 1-2 分钟)
REM   --cpu_offload      把不用的层卸到 CPU
REM   --overlapped_decode  分段解码,峰值显存更低
python app.py --port 7860 --bf16 true --torch_compile true --cpu_offload true --overlapped_decode true

pause
