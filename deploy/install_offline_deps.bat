@echo off
setlocal
cd /d "%~dp0\.."

python -m pip install ^
  --no-index ^
  --find-links offline_wheels ^
  -r requirements.txt ^
  -r requirements-build.txt

echo.
echo Offline dependencies installed.
pause
