@echo off
cd /d "%~dp0..\backend"
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
)
set PYTHONPATH=.
.venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
