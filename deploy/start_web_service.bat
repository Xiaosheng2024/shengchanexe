@echo off
setlocal
cd /d "%~dp0\.."

if exist "dist\WebAdminService.exe" (
  "dist\WebAdminService.exe"
) else (
  python web_admin.py
)
