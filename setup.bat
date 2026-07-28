@echo off
chcp 65001 >nul
echo ========================================
echo   ETF Pipeline - 一键初始化
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 创建虚拟环境...
python -m venv .venv
if %errorlevel% neq 0 (
    echo 错误: 创建 venv 失败，请确认 Python 3.10+ 已安装
    pause
    exit /b 1
)

echo [2/3] 安装依赖...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 错误: 安装依赖失败
    pause
    exit /b 1
)

echo [3/3] 安装 PyInstaller...
.venv\Scripts\python.exe -m pip install pyinstaller -q

echo.
echo 初始化完成! 运行以下命令启动:
echo   .venv\Scripts\python.exe gui.py
echo.
pause
