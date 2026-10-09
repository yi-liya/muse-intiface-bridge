@echo off
REM 启动 ESP32-S3 固件烧录工具（无黑框）
REM 要完全不闪请双击 启动烧录工具.vbs

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
    start "" "%PYW%" "%~dp0烧录工具.py"
) else (
    start "" py -3.11 "%~dp0烧录工具.py"
)
exit /b