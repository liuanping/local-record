@echo off
rem ============================================================
rem Local Record 一键运行（开发模式，双击即可）
rem 首次运行会自动建 .venv 并安装依赖（走清华镜像，约 5-10 分钟）
rem ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 首次运行：创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [错误] 未找到 Python 或创建 venv 失败。
        echo        请先安装 Python 3.11+（勾选 Add to PATH）后重试。
        pause
        exit /b 1
    )
    echo [2/2] 安装依赖（清华镜像，约 5-10 分钟）...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

echo 正在启动 Local Record（首次启动需等待大模型加载约 1 分钟）...
".venv\Scripts\python.exe" -m app.main
pause
