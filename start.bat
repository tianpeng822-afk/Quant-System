@echo off
cd /d "%~dp0"
call .venv\Scripts\activate

REM 启动后台定时任务
start /b python main.py

REM 启动前端网页
start /b streamlit run web/0_首页.py --server.port=8501 --server.address=0.0.0.0
