@echo off
setlocal
cd /d "%~dp0\.."

python -m pip install ^
  --no-index ^
  --find-links offline_wheels ^
  -r requirements-client.txt ^
  -r requirements-dev.txt

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name QualityControlSystem ^
  main.py

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name WebAdminService ^
  web_admin.py

echo.
echo Build finished:
echo   dist\QualityControlSystem.exe
echo   dist\WebAdminService.exe
pause
