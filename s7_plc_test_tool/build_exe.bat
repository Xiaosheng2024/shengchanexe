@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
pyinstaller --noconfirm --onefile --windowed --name S7_PLC_Test_Tool main.py
echo.
echo 打包完成，EXE位置：dist\S7_PLC_Test_Tool.exe
pause
