@echo off
cd /d "%~dp0..\.."

echo Checking Python...
python --version

echo Installing requirements...
pip install -r requirements.txt

echo Done!
pause
