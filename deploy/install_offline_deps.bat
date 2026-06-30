@echo off
setlocal
cd /d "%~dp0\.."

python -m pip install ^
  --no-index ^
  --find-links offline_wheels ^
  -r requirements-client.txt ^
  -r requirements-dev.txt

echo.
echo Offline dependencies installed.
pause
