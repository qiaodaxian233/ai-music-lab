@echo off
chcp 65001 >nul
title AI Music Lab - 后处理监视器
echo.
echo 监视 outputs\ 自动归一化新生成的歌
echo 关闭窗口停止服务
echo.

call .venv\Scripts\activate.bat
python scripts\auto-postprocess.py
pause
