#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  Vestige -- DnD AI Avatar System -- Install"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python ──────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.12+."
    exit 1
fi
PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[OK] Python $PYVER"

# ── Check Node ────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    echo "[ERROR] Node.js not found. Install Node.js 20+ from https://nodejs.org"
    exit 1
fi
echo "[OK] Node.js $(node --version)"

# ── Check npm ─────────────────────────────────────────────────
if ! command -v npm &>/dev/null; then
    echo "[ERROR] npm not found. Reinstall Node.js."
    exit 1
fi
echo "[OK] npm $(npm --version)"

echo

# ── .env setup ───────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[SETUP] Copying .env.example -> .env"
    cp .env.example .env
    echo
    echo " ** ACTION REQUIRED **"
    echo " Edit .env and set your ANTHROPIC_API_KEY before starting."
    echo " File: $SCRIPT_DIR/.env"
    echo
else
    echo "[OK] .env already exists"
fi

# ── Backend venv ─────────────────────────────────────────────
echo "[BACKEND] Setting up Python virtual environment..."
cd backend

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment already exists"
fi

echo "[BACKEND] Installing Python dependencies..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt
echo "[OK] Backend dependencies installed"

# ── Create data dir ──────────────────────────────────────────
mkdir -p ../data

cd ..

# ── Frontend deps ─────────────────────────────────────────────
echo
echo "[FRONTEND] Installing Node dependencies..."
cd frontend
npm install
echo "[OK] Frontend dependencies installed"
cd ..

# ── Ollama reminder ───────────────────────────────────────────
echo
if command -v ollama &>/dev/null; then
    echo "[OK] Ollama found"
else
    echo "[WARN] Ollama not found."
    echo "       Install from https://ollama.ai and run:"
    echo "         ollama pull llama3.1:8b"
fi

# ── Done ──────────────────────────────────────────────────────
echo
echo "============================================================"
echo "  Install complete!"
echo "============================================================"
echo
echo "  Start backend:   cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000"
echo "  Start frontend:  cd frontend && npm run dev"
echo
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo

if grep -q "sk-ant-\.\.\." .env 2>/dev/null; then
    echo " ** Don't forget to add your ANTHROPIC_API_KEY to .env **"
    echo
fi
