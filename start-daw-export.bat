@echo off
chcp 65001 >nul
title AI Music Lab - Song to DAW Export (端口 7863)
echo.
echo Song to DAW Export: http://localhost:7863
echo.

call .venv\Scripts\activate.bat
python scripts\song-to-daw.py
pause
