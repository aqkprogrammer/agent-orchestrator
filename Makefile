.DEFAULT_GOAL := help
API_PORT ?= 8000

.PHONY: help install dev api worker ui test lint format typecheck check up down logs demo clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and frontend dependencies
	uv sync
	cd frontend && npm ci

dev: ## Run API (no-infra mock mode) and the Vite dev server together
	@trap 'kill 0' INT TERM; \
	API_PORT=$(API_PORT) uv run orchestrator-api & \
	cd frontend && VITE_API_PROXY=http://127.0.0.1:$(API_PORT) npm run dev & \
	wait

api: ## Run only the API
	API_PORT=$(API_PORT) uv run orchestrator-api

worker: ## Run a Celery worker (requires REDIS_URL and RUN_EXECUTOR=celery)
	uv run celery -A orchestrator.worker.celery_app worker --loglevel=INFO -Q runs

ui: ## Run only the Vite dev server
	cd frontend && VITE_API_PROXY=http://127.0.0.1:$(API_PORT) npm run dev

test: ## Run the Python test-suite (offline)
	uv run pytest

lint: ## Lint Python and TypeScript
	uv run ruff check .
	uv run ruff format --check .
	cd frontend && npm run lint

format: ## Auto-format Python code
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Static type checks (mypy + tsc)
	uv run mypy src
	cd frontend && npm run typecheck

check: lint typecheck test ## Everything CI runs
	cd frontend && npm run build

up: ## Build and start the full stack (Postgres, Redis, Chroma, API, worker, UI)
	docker compose up -d --build

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Tail stack logs
	docker compose logs -f api worker

demo: ## Drive the end-to-end HITL demo against a running API
	./scripts/demo.sh http://localhost:$(API_PORT)

clean: ## Remove local data and caches
	rm -rf data .pytest_cache .ruff_cache .mypy_cache frontend/dist
