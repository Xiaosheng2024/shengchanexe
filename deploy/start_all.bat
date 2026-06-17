@echo off
setlocal
cd /d "%~dp0\.."

start "WebAdminService" deploy\start_web_service.bat
timeout /t 2 >nul
start "QualityControlSystem" deploy\start_desktop.bat
