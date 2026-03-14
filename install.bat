@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Vestige -- DnD AI Avatar System -- Install
echo ============================================================
echo.

:: ── Check Python ─────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.12+ from https://python.org
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER%

:: ── Check Node ────────────────────────────────────────────────
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 20+ from https://nodejs.org
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo [OK] Node.js %NODEVER%

:: ── Check npm ─────────────────────────────────────────────────
npm --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Reinstall Node.js.
    exit /b 1
)
echo [OK] npm found

echo.

:: ── .env setup ───────────────────────────────────────────────
if not exist ".env" (
    echo [SETUP] Copying .env.example -> .env
    copy ".env.example" ".env" >nul
    echo.
    echo  ** ACTION REQUIRED **
    echo  Edit .env and set your ANTHROPIC_API_KEY before starting.
    echo  File: %CD%\.env
    echo.
) else (
    echo [OK] .env already exists
)

:: ── Backend venv ─────────────────────────────────────────────
echo [BACKEND] Setting up Python virtual environment...
cd backend

if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

echo [BACKEND] Installing Python dependencies...
.venv\Scripts\pip install --upgrade pip --quiet
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Check requirements.txt and your Python version.
    exit /b 1
)
echo [OK] Backend dependencies installed

:: ── PyTorch with CUDA ─────────────────────────────────────────
echo [GPU] Installing PyTorch with CUDA 12.4 support...
.venv\Scripts\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 --quiet
if errorlevel 1 (
    echo [WARN] PyTorch CUDA install failed. Trying CPU-only fallback...
    .venv\Scripts\pip install torch torchaudio --quiet
)
echo [OK] PyTorch installed

:: ── Create data dir ──────────────────────────────────────────
if not exist "..\data" (
    mkdir "..\data"
    echo [OK] Created data/ directory
)

cd ..

:: ── Frontend deps ─────────────────────────────────────────────
echo.
echo [FRONTEND] Installing Node dependencies...
cd frontend
npm install
if errorlevel 1 (
    echo [ERROR] npm install failed.
    exit /b 1
)
echo [OK] Frontend dependencies installed
cd ..

:: ── Ollama reminder ───────────────────────────────────────────
echo.
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Ollama not found in PATH.
    echo        Install from https://ollama.ai and run:
    echo          ollama pull llama3.1:8b
) else (
    echo [OK] Ollama found
)

:: ── Done ──────────────────────────────────────────────────────
echo.
echo ============================================================
echo   Install complete!
echo ============================================================
echo.
echo   Start backend:   scripts\start_backend.bat
echo   Start frontend:  cd frontend ^&^& npm run dev
echo.
echo   Or run both at once:   scripts\start_all.bat
echo.
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo.
if not exist ".env" goto :eof
findstr /c:"sk-ant-..." ".env" >nul 2>&1
if not errorlevel 1 (
    echo  ** Don't forget to add your ANTHROPIC_API_KEY to .env **
    echo.
)
endlocal
