@echo off
chcp 65001 >nul
title AI Music Lab - 历史浏览器 (端口 7861)
echo.
echo 历史浏览器: http://localhost:7861
echo.

call .venv\Scripts\activate.bat
python scripts\history-ui.py
pause
