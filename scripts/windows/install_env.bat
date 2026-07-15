@echo off
chcp 65001 >nul
echo ========================================
echo   正在为 MyFund-Quant-System 安装依赖库
echo ========================================

cd /d %~dp0\..\..

:: 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先在服务器上安装 Python 3.10 以上版本，并将其添加到 PATH 环境变量。
    pause
    exit /b
)

:: 安装依赖
echo 正在安装必要的 Python 库 (可能需要几分钟)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [错误] 安装依赖库失败，请检查网络连接或更换国内 pip 源。
    pause
    exit /b
)

echo.
echo [成功] 所有依赖已安装完毕！现在你可以双击运行 start_web.bat 了。
pause
