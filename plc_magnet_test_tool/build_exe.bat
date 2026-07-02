@echo off
setlocal
cd /d "%~dp0.."

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name PLC_Magnet_Test_Tool ^
  --paths . ^
  --hidden-import shared ^
  --hidden-import shared.s7_plc_client ^
  --add-data "config.example.ini;." ^
  --distpath plc_magnet_test_tool\dist ^
  --workpath plc_magnet_test_tool\build ^
  --specpath plc_magnet_test_tool ^
  plc_magnet_test_tool\main.py

if errorlevel 1 exit /b 1
echo Built: plc_magnet_test_tool\dist\PLC_Magnet_Test_Tool.exe
