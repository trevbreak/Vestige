@echo off
echo Starting Vestige — AI Avatar System
echo =====================================
echo.

REM ── Ollama ─────────────────────────────────────────────────────────────────
echo [1/3] Checking Ollama...

REM Check if ollama is on PATH
where ollama >nul 2>&1
if errorlevel 1 (
    echo   WARNING: ollama not found on PATH. Skipping — LLM calls will fall back to Claude API.
    goto :skip_ollama
)

REM Check if Ollama is already running
curl -s http://localhost:11434 >nul 2>&1
if not errorlevel 1 (
    echo   Ollama already running on port 11434.
    goto :skip_ollama
)

echo   Starting Ollama server...
start "Vestige Ollama" cmd /k "ollama serve"
timeout /t 3 /nobreak >nul

REM Ensure the required model is pulled
echo   Ensuring llama3.1:8b model is available...
start "Vestige Ollama Pull" cmd /c "ollama pull llama3.1:8b"

:skip_ollama
echo.

REM ── Cleanup old processes ──────────────────────────────────────────────────
echo [2/3] Cleaning up old processes...

REM Kill any process using port 8000 (backend)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    echo   Killing backend process PID %%p on port 8000
    taskkill /PID %%p /F >nul 2>&1
)

REM Kill any process using port 5173 (frontend)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING') do (
    echo   Killing frontend process PID %%p on port 5173
    taskkill /PID %%p /F >nul 2>&1
)

REM Close any existing Vestige console windows by title
taskkill /FI "WINDOWTITLE eq Vestige Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Vestige Frontend" /F >nul 2>&1

timeout /t 1 /nobreak >nul
echo.

REM ── Backend + Frontend ────────────────────────────────────────────────────
echo [3/3] Starting services...

start "Vestige Backend" cmd /k "cd /d "%~dp0..\backend" && .venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 2 /nobreak >nul
start "Vestige Frontend" cmd /k "cd /d "%~dp0..\frontend" && npm run dev"

echo.
echo =====================================
echo   Ollama:   http://localhost:11434
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo =====================================
