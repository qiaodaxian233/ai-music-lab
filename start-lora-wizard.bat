@echo off
chcp 65001 >nul
title AI Music Lab - LoRA 训练向导 (端口 7862)
echo.
echo LoRA 训练向导: http://localhost:7862
echo.

call .venv\Scripts\activate.bat
python scripts\lora-wizard.py
pause
