@echo off
chcp 65001 >nul
title Sing-Box v1.13.13
cd /d D:\PYTHON\Singbox
echo ================================
echo      Sing-Box v1.13.13
echo ================================
echo.

if not exist "config.json" (
    echo [ERROR] config.json not found!
    echo Please place your config file here:
    echo %cd%\config.json
    echo.
    pause
    exit /b 1
)

echo Starting Sing-Box...
echo Press Ctrl+C to stop.
echo.
sing-box.exe run -c config.json
echo.
echo Sing-Box stopped.
pause
