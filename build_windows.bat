@echo off
setlocal

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

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
