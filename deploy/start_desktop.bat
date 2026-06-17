@echo off
setlocal
cd /d "%~dp0\.."

if exist "dist\QualityControlSystem.exe" (
  "dist\QualityControlSystem.exe"
) else (
  python main.py
)
