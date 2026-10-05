@echo off
rem ============================================================
rem Local Record 一键打包（双击即可，内部调用 Git Bash）
rem 等价于: ./scripts/package_windows.sh
rem 传参:  --skip-checks  模型没放齐也能出包（运行时对应功能不可用）
rem         --no-iss      不生成 Inno Setup 安装器
rem ============================================================
cd /d "%~dp0"

rem ---- 定位 Git Bash（PATH 或常见安装位置）----
set "BASH_EXE="
where bash >nul 2>nul
if not errorlevel 1 set "BASH_EXE=bash"
if not defined BASH_EXE if exist "E:\Git\bin\bash.exe" set "BASH_EXE=E:\Git\bin\bash.exe"
if not defined BASH_EXE if exist "E:\Git\usr\bin\bash.exe" set "BASH_EXE=E:\Git\usr\bin\bash.exe"
if not defined BASH_EXE if exist "C:\Program Files\Git\bin\bash.exe" set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"
if not defined BASH_EXE if exist "C:\Program Files\Git\usr\bin\bash.exe" set "BASH_EXE=C:\Program Files\Git\usr\bin\bash.exe"
if not defined BASH_EXE if exist "D:\Git\bin\bash.exe" set "BASH_EXE=D:\Git\bin\bash.exe"
if not defined BASH_EXE if exist "D:\Git\usr\bin\bash.exe" set "BASH_EXE=D:\Git\usr\bin\bash.exe"
if not defined BASH_EXE (
    echo [错误] 未找到 Git Bash。打包脚本需要 Git for Windows：
    echo         https://git-scm.com/download/win
    pause
    exit /b 1
)

echo 开始打包（约 10 分钟，需要 15GB 磁盘空间）...
"%BASH_EXE%" scripts/package_windows.sh %*
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方输出。
) else (
    echo.
    echo [完成] 产物在 dist\ 目录：LocalRecord.exe / LocalRecord-windows-x64.zip
)
pause
