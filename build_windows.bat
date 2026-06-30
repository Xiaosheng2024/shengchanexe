@echo off
setlocal

python -m pip install --upgrade pip
python -m pip install -r requirements-client.txt -r requirements-dev.txt

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name QualityControlSystem ^
  main.py

echo.
echo Build finished. EXE path: dist\QualityControlSystem.exe
pause
