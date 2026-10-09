@echo off
REM 启动暮瑟控制台（无黑框）
REM 双击本文件时窗口会一闪而过；要完全不闪请双击 启动控制台.vbs

cd /d "%~dp0"

set "PYW="
for %%P in (
    "%LocalAppData%\Programs\Python\Python311\pythonw.exe"
    "%LocalAppData%\Programs\Python\Python312\pythonw.exe"
    "%LocalAppData%\Programs\Python\Python313\pythonw.exe"
) do (
    if exist %%P if not defined PYW set "PYW=%%~P"
)

if defined PYW (
    start "" "%PYW%" "%~dp0main.py"
) else (
    start "" py -3.11 "%~dp0main.py"
)
exit /b