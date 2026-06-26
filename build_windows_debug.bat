@echo off
setlocal

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name QualityControlSystem_Debug ^
  main.py

echo.
echo Debug build finished. EXE path: dist\QualityControlSystem_Debug.exe
pause
