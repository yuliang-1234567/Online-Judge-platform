UV ?= uv
COMPOSE := docker compose --env-file deploy/.env -f deploy/docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help install run test lint fmt dev-config dev-up dev-down dev-ps dev-check probe

help:
	@echo "install     Sync locked backend dependencies"
	@echo "run         Run the local API"
	@echo "test        Run pytest"
	@echo "probe       Run explicit Docker file/permission probes (build image first)"
	@echo "lint        Check Ruff lint and formatting"
	@echo "fmt         Format backend Python files"
	@echo "dev-config  Validate Compose without printing secrets"
	@echo "dev-up      Start MySQL and Redis and wait for health checks"
	@echo "dev-check   Verify MySQL ping/login and Redis ping"
	@echo "dev-ps      Show development service status"
	@echo "dev-down    Stop services and keep data volumes"

install:
	cd backend && $(UV) sync --locked

run:
	cd backend && $(UV) run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000

test:
	cd backend && $(UV) run --locked pytest

lint:
	cd backend && $(UV) run --locked ruff check .
	cd backend && $(UV) run --locked ruff format --check .

fmt:
	cd backend && $(UV) run --locked ruff format .

dev-config:
	$(COMPOSE) config --quiet

dev-up:
	@if [ ! -f deploy/.env ]; then \
		printf '%s\n' "缺少 deploy/.env：先 cp deploy/.env.example deploy/.env 再填凭据"; \
		exit 1; \
	fi
	$(COMPOSE) up -d --wait --wait-timeout 180

dev-down:
	$(COMPOSE) down

dev-ps:
	$(COMPOSE) ps

dev-check:
	$(COMPOSE) exec -T --user mysql mysql sh -ec 'MYSQL_PWD="$$MYSQL_PASSWORD" mysqladmin ping --host=127.0.0.1 --user="$$MYSQL_USER" --silent'
	$(COMPOSE) exec -T --user mysql mysql sh -ec 'MYSQL_PWD="$$MYSQL_PASSWORD" mysql --host=127.0.0.1 --user="$$MYSQL_USER" --database="$$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT 1"'
	$(COMPOSE) exec -T --user redis redis sh -ec 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping'

probe:
	cd backend && $(UV) run --locked --offline pytest -o addopts="" -m docker -s -x
