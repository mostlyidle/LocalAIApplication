.PHONY: setup dev dev-backend dev-frontend dev-desktop test-desktop-launcher test test-backend test-frontend lint format migrate seed clean help docker-up docker-down docker-infra docker-app docker-build docker-test docker-observability docker-logs docker-clean

# =============================================================================
# Local AI Application — Makefile
# =============================================================================

BACKEND_DIR = backend
FRONTEND_DIR = frontend

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: ## Install all dependencies and pull Ollama models
	@echo "==> Installing backend dependencies..."
	uv sync --project $(BACKEND_DIR)
	@echo "==> Installing frontend dependencies..."
	cd $(FRONTEND_DIR) && pnpm install
	@echo "==> Pulling Ollama models..."
	ollama pull laya:latest
	ollama pull llama3.1:8b
	ollama pull qwen2.5:7b
	ollama pull qwen3-vl:4b
	ollama pull qwen2.5-coder:7b
	ollama pull nomic-embed-text
	@echo "==> Copying environment files..."
	@test -f .env || cp .env.example .env
	@test -f $(FRONTEND_DIR)/.env.local || echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > $(FRONTEND_DIR)/.env.local
	@echo "==> Creating data directories..."
	mkdir -p data/uploads data/chroma data/fastembed
	@echo "==> Running database migrations..."
	uv run --project $(BACKEND_DIR) alembic -c $(BACKEND_DIR)/alembic.ini upgrade head
	@echo "==> Setup complete!"

setup-backend: ## Install backend dependencies only
	cd $(BACKEND_DIR) && uv sync

setup-frontend: ## Install frontend dependencies only
	cd $(FRONTEND_DIR) && pnpm install

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

dev: ## Start backend + frontend concurrently
	@make dev-backend & make dev-frontend

dev-backend: ## Start FastAPI backend with hot reload
	uv run --project $(BACKEND_DIR) uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Start Next.js frontend dev server
	cd $(FRONTEND_DIR) && pnpm dev

dev-desktop: ## Run the supervised local desktop workflow
	bash scripts/run-desktop-local.sh

test-desktop-launcher: ## Run deterministic desktop launcher supervision checks
	bash scripts/run-desktop-local.sh --self-test

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests with coverage
	cd $(BACKEND_DIR) && uv run pytest -v --cov=app --cov-report=term-missing

test-frontend: ## Run frontend tests
	cd $(FRONTEND_DIR) && pnpm test

test-e2e: ## Run end-to-end tests
	cd $(FRONTEND_DIR) && pnpm test:e2e

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

lint: ## Run linters (ruff + eslint)
	cd $(BACKEND_DIR) && uv run ruff check app/ tests/
	cd $(FRONTEND_DIR) && pnpm lint

format: ## Auto-format all code
	cd $(BACKEND_DIR) && uv run ruff format app/ tests/
	cd $(BACKEND_DIR) && uv run ruff check --fix app/ tests/
	cd $(FRONTEND_DIR) && pnpm format

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate: ## Run database migrations
	uv run --project $(BACKEND_DIR) alembic -c $(BACKEND_DIR)/alembic.ini upgrade head

migrate-new: ## Create a new migration (usage: make migrate-new MSG="add users table")
	uv run --project $(BACKEND_DIR) alembic -c $(BACKEND_DIR)/alembic.ini revision --autogenerate -m "$(MSG)"

seed: ## Seed demo database with sample data
	cd $(BACKEND_DIR) && uv run python ../scripts/seed_demo_db.py

# ---------------------------------------------------------------------------
# MCP Servers
# ---------------------------------------------------------------------------

mcp-sql: ## Start SQL MCP server
	cd $(BACKEND_DIR) && uv run python -m app.mcp.servers.sql_server

mcp-document: ## Start Document MCP server
	cd $(BACKEND_DIR) && uv run python -m app.mcp.servers.document_server

mcp-rag: ## Start RAG MCP server
	cd $(BACKEND_DIR) && uv run python -m app.mcp.servers.rag_server

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches, build artifacts, temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND_DIR)/dist $(BACKEND_DIR)/build
	rm -rf htmlcov .coverage
	@echo "Cleaned."

clean-data: ## Remove all runtime data (uploads, vector store, databases)
	rm -rf data/
	mkdir -p data/uploads data/chroma data/fastembed
	@echo "Data directories reset."

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

docker-up: ## Start all services (infra + app) via Docker Compose
	docker compose --profile full up -d --build
	@echo "==> All services starting. Run 'make docker-logs' to follow."

docker-down: ## Stop all Docker Compose services
	docker compose --profile full down
	@echo "==> All services stopped."

docker-infra: ## Start infrastructure only (Ollama + Qdrant + ChromaDB migration source)
	docker compose --profile infra up -d
	@echo "==> Infrastructure services starting."

docker-app: ## Start backend + frontend + Qdrant — assumes Ollama is running natively
	docker compose --profile app up -d --build
	@echo "==> Application services starting."

docker-build: ## Build Docker images without starting
	docker compose --profile full build
	@echo "==> Images built."

docker-test: ## Build and run backend tests in the isolated test image target
	docker build --target test -t local-ai-backend:test ./backend
	docker run --rm local-ai-backend:test

docker-observability: ## Start the app with optional Prometheus and Grafana
	docker compose --profile app --profile observability up -d --build
	@echo "==> App and observability services starting."

docker-logs: ## Follow logs from all running services
	docker compose --profile full logs -f

docker-clean: ## Remove all containers, images, and volumes for this project
	docker compose --profile full down -v --rmi local
	@echo "==> Docker resources cleaned."
