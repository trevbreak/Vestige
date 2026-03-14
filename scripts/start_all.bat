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

REM Kill by window title first
taskkill /FI "WINDOWTITLE eq Vestige Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Vestige Frontend" /F >nul 2>&1

REM Kill every process on port 8000 — catches stale uvicorn --reload child workers
REM that survive a window-title kill because the reloader spawns children with different titles
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    echo   Killing process PID %%p on port 8000
    taskkill /PID %%p /F >nul 2>&1
)

REM Kill port 5173 (Vite dev server)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr LISTENING') do (
    echo   Killing process PID %%p on port 5173
    taskkill /PID %%p /F >nul 2>&1
)

REM Wait for OS to release ports and for dying processes to free CUDA memory
timeout /t 3 /nobreak >nul

REM Warn if port 8000 is still occupied
netstat -ano | findstr ":8000 " | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    echo   WARNING: port 8000 still in use — a stale process may interfere. Consider rebooting.
)
echo.

REM ── Backend + Frontend ────────────────────────────────────────────────────
echo [3/3] Starting services...

start "Vestige Backend" cmd /k "cd /d "%~dp0..\backend" && .venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM Wait for backend to accept connections before starting frontend.
REM Model loading (Whisper/TTS/VAD) can take 30-60s on first run.
echo   Waiting for backend to be ready on port 8000...
:wait_backend
timeout /t 2 /nobreak >nul
curl -s http://localhost:8000/api/settings >nul 2>&1
if errorlevel 1 goto :wait_backend
echo   Backend ready.

start "Vestige Frontend" cmd /k "cd /d "%~dp0..\frontend" && npm run dev"

echo.
echo =====================================
echo   Ollama:   http://localhost:11434
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo =====================================
