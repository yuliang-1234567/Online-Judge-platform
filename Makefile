# 从仓库根调用；UV 可由命令行覆盖，WSL 可传绝对路径而不改项目配置。
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

# 依赖按锁文件同步；--locked 要求声明与锁一致，不能在这些入口中悄悄重算锁。
install:
	cd backend && $(UV) sync --locked

# 在 backend 内运行以统一模块导入与工具配置；&& 保证切目录失败后不会继续。
run:
	cd backend && $(UV) run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000

test:
	cd backend && $(UV) run --locked pytest

lint:
	cd backend && $(UV) run --locked ruff check .
	cd backend && $(UV) run --locked ruff format --check .

fmt:
	cd backend && $(UV) run --locked ruff format .

# 只检查 Compose 配置，不展开打印含真实凭据的环境值。
dev-config:
	$(COMPOSE) config --quiet

# 缺少本地配置立即失败；--wait 等健康检查，容器启动不等于服务已可用。
dev-up:
	@if [ ! -f deploy/.env ]; then \
		printf '%s\n' "缺少 deploy/.env：先 cp deploy/.env.example deploy/.env 再填凭据"; \
		exit 1; \
	fi
	$(COMPOSE) up -d --wait --wait-timeout 180

# 停服务但保留命名数据卷；此入口不是清空开发数据库。
dev-down:
	$(COMPOSE) down

dev-ps:
	$(COMPOSE) ps

# $$ 是 make 的转义，最终交给容器内 shell 展开；写成单个 $ 会被 make 吃掉。
dev-check:
	$(COMPOSE) exec -T --user mysql mysql sh -ec 'MYSQL_PWD="$$MYSQL_PASSWORD" mysqladmin ping --host=127.0.0.1 --user="$$MYSQL_USER" --silent'
	$(COMPOSE) exec -T --user mysql mysql sh -ec 'MYSQL_PWD="$$MYSQL_PASSWORD" mysql --host=127.0.0.1 --user="$$MYSQL_USER" --database="$$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT 1"'
	$(COMPOSE) exec -T --user redis redis sh -ec 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping'

# 此入口清空默认 addopts 后选择 docker；同时会移除 --strict-markers 的拼写校验。
# -x 在首个失败时停止，探针自身负责清理；普通 test 不运行这些场景。
probe:
	cd backend && $(UV) run --locked --offline pytest -o addopts="" -m docker -s -x
