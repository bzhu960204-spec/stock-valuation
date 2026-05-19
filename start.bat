@echo off
chcp 65001 >nul
title Stock Valuation

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   Stock Valuation - 一键启动        ║
echo  ╚══════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: Try to create venv, fallback to global if fails
if not exist ".venv\Scripts\activate.bat" (
    echo  [INFO] 创建虚拟环境...
    python -m venv .venv 2>nul
)

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo  [INFO] 安装/更新依赖...
python -m pip install -r requirements.txt -q

echo.
echo  [INFO] 启动服务...
echo  [INFO] 访问 http://localhost:5000
echo  [INFO] 按 Ctrl+C 停止
echo.

python app.py
