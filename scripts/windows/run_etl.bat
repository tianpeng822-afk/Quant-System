@echo off
cd /d "%~dp0..\.."

echo Starting ETL Job...
python -c "from app.pipeline import run_daily_etl; run_daily_etl()"

timeout /t 3 /nobreak >nul
