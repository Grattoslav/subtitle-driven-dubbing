@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo "Starting S.bros Video Diarization & ASR..."
set PYTHONPATH=%PYTHONPATH%;%CD%
python system/dabing_gui.py
pause
