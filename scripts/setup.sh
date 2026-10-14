#!/usr/bin/env bash
# =============================================================================
# Local AI Application — Full Setup Script
# =============================================================================
# Usage: bash scripts/setup.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Check prerequisites ────────────────────────────────────────────────
info "Checking prerequisites..."

command -v ollama >/dev/null 2>&1 || error "Ollama not found. Install with: brew install ollama"
command -v uv     >/dev/null 2>&1 || error "uv not found. Install with: brew install uv"
command -v pnpm   >/dev/null 2>&1 || error "pnpm not found. Install with: brew install pnpm"
command -v node   >/dev/null 2>&1 || error "Node.js not found. Install with: brew install node"

info "All prerequisites found."

# ── Environment files ──────────────────────────────────────────────────
info "Setting up environment files..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ ! -f .env ]; then
    cp .env.example .env
    info "Created .env from .env.example"
else
    info ".env already exists, skipping."
fi

if [ ! -f frontend/.env.local ]; then
    echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
    info "Created frontend/.env.local"
else
    info "frontend/.env.local already exists, skipping."
fi

# ── Data directories ───────────────────────────────────────────────────
info "Creating data directories..."
mkdir -p data/uploads data/chroma data/fastembed

# ── Backend setup ──────────────────────────────────────────────────────
info "Installing backend dependencies..."
uv sync --project "$PROJECT_DIR/backend"

# ── Frontend setup ─────────────────────────────────────────────────────
info "Installing frontend dependencies..."
pnpm --dir "$PROJECT_DIR/frontend" install

# ── Ollama models ──────────────────────────────────────────────────────
info "Checking Ollama status..."

if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    warn "Ollama is not running. Starting Ollama..."
    ollama serve &
    sleep 3
fi

MODELS=("llama3.1:8b" "nomic-embed-text" "llama3.2-vision:11b")

for model in "${MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "$model"; then
        info "Model $model already pulled."
    else
        info "Pulling model $model (this may take a while)..."
        ollama pull "$model"
    fi
done

# ── Database migrations ────────────────────────────────────────────────
info "Running database migrations..."
uv run --project "$PROJECT_DIR/backend" alembic -c "$PROJECT_DIR/backend/alembic.ini" upgrade head

# ── Done ───────────────────────────────────────────────────────────────
echo ""
info "=============================================="
info "  Setup complete!"
info "=============================================="
info ""
info "  Start the application:"
info "    make dev"
info ""
info "  Or start individually:"
info "    make dev-backend   (FastAPI on :8000)"
info "    make dev-frontend  (Next.js on :3000)"
info ""
