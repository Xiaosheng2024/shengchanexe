@echo off
cd /d "%~dp0.."
python -m pip install -r requirements-client.txt -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name S7_PLC_Test_Tool ^
  --paths . ^
  --hidden-import shared ^
  --hidden-import shared.s7_plc_client ^
  --add-data "s7_plc_test_tool\config.ini;." ^
  --distpath s7_plc_test_tool\dist ^
  --workpath s7_plc_test_tool\build ^
  s7_plc_test_tool\main.py
echo.
echo 打包完成，EXE位置：s7_plc_test_tool\dist\S7_PLC_Test_Tool.exe
pause
