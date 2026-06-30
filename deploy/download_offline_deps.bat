@echo off
setlocal
cd /d "%~dp0\.."

if not exist offline_wheels mkdir offline_wheels

python -m pip install --upgrade pip
python -m pip download ^
  --dest offline_wheels ^
  -r requirements-client.txt ^
  -r requirements-dev.txt

echo.
echo Offline dependency wheels saved to: offline_wheels
pause
