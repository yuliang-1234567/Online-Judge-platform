# OJ 在线判题系统

Python 后端求职项目，目标是实现题库、异步判题与结果查询。需求以 [项目设计](docs/project-design.md) 为准。

## 当前进度

| 编号 | 这一节做什么 | 状态 | 对应提交 |
| --- | --- | --- | --- |
| 06.1 | 仓库规则、换行约定、环境变量模板 | 已完成 | b34da9e / c7738ce |
| 06.2 | 后端骨架：uv、Ruff、pytest、/healthz | 已完成 | f71c890 / b52f128 |
| 06.3 | MySQL 与 Redis 开发服务、Makefile | 已完成 | 4ecde79 |
| 06.4 | pre-commit、最小 CI、README | 已完成 | f27c93e / 6099783 |
| 06.5 | 判题环境探针（Docker 文件与权限链路） | 未开始 | 待 Docker 网络验收 |

1. 日期依据是 [设计文档 §17.2「重排执行表」](docs/project-design.md#172-重排执行表)（第1645—1662行）；06.5 对应其中「阶段06末尾，限半天」那一行。
2. 06.x 是阶段06内部的施工编号，设计文档没有这一层编号。
3. 06.1—06.3 于 2026-10-19 完成，早于 §17.2 的计划窗口，原因是 Docker 网络问题未阻塞主线；如实记录，不为了对齐计划表而改日期。

当前只实现 `GET /healthz`，返回 `200` 和 `{"status":"ok"}`；它只检查 API 进程存活，不检查 MySQL 或 Redis。其余业务接口、数据库迁移与判题流程均未实现；没有演示账号。MySQL/Redis 是本地开发依赖，API 在 WSL 本地运行。

远端 Actions 未验证，待首次推送后确认；届时将运行结果补入 [验证记录](docs/evidence/06.4-local-checks.md)。当前工作流仅覆盖后端 Ruff 与已有 pytest 用例。

## 前置环境

- WSL2 + Ubuntu 24.04；工程放在 Linux 文件系统，例如 `~/projects/oj-platform`，不用 `/mnt/d`。
- Ubuntu 内的原生 Docker Engine 与 Compose 插件，当前普通用户可以运行 Docker。
- uv、GNU make、Git；Ubuntu 自带 Python 3.12，项目也固定使用 Python 3.12。
- 官方 PyPI、GitHub 可达；daemon 能拉取官方 MySQL/Redis 镜像。

在 WSL 终端确认 `docker version` 同时显示 Client/Server，`docker compose version`、`uv --version`、`make --version` 均可用。uv 当前使用 0.13.1；安装说明见 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/)，Docker 安装见 [Ubuntu 官方安装说明](https://docs.docker.com/engine/install/ubuntu/)。工具尚未装好时先完成环境准备。

## 从零启动

以下命令均在 WSL Ubuntu 中执行；假定仓库已放到上述目录。

```bash
cd ~/projects/oj-platform
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
```

复制只做一次；已有 `deploy/.env` 时保留原配置，不覆盖。用编辑器填写 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`REDIS_PASSWORD`，三者使用不同的本地密码。可分别运行 `python3 -c 'import secrets; print(secrets.token_hex(32))'` 生成不含 URL 特殊字符的值。保留模板中的数据库名和用户名；把连接 URL 中的 `REPLACE_ME` 分别替换成对应密码。`JWT_SECRET` 另行生成填写，目前 `/healthz` 尚未加载这些配置。真实 `.env` 已被 Git 忽略，不要提交。

```bash
make install
uv run --project backend --locked pre-commit install
uv run --project backend --locked pre-commit run --all-files
make dev-up
make dev-check
make test
make lint
make run
```

`make install` 按锁文件安装依赖；`make dev-up` 只启动 MySQL/Redis 并等待健康检查。`make dev-check` 应依次得到 `mysqld is alive`、查询结果 `1`、`PONG`。pytest 当前只有一个存活接口用例。

`make run` 在前台启动 API，保留该终端；另开一个 WSL 终端执行：

```bash
curl --fail --show-error http://127.0.0.1:8000/healthz
```

预期响应 `{"status":"ok"}`。Swagger 地址为 `http://127.0.0.1:8000/docs`。用 Ctrl+C 停止 API；`make dev-down` 停止依赖服务并保留数据卷。

## 检查与 CI

本地钩子只运行 Ruff lint 和格式检查，使用 `v0.17.1`，不会自动修复文件。格式问题可先看报错，再主动执行 `make fmt`。首次运行钩子会从官方 GitHub/PyPI 安装隔离环境。

[ci.yml](.github/workflows/ci.yml) 使用 Python 3.12、uv 0.13.1，权限为 `contents: read`。在仓库根目录执行下列命令，可以复现其所有 `run` 步骤：

```bash
cd backend
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

## 排障

- **缺少配置**：缺 .env 时 make 返回 2 属正常。应看到中文提示；先复制模板并填写凭据，再运行 `make dev-up`。不要用忽略错误的方式绕过失败。
- **13306/16379 被占用**：Compose 会报告端口无法绑定。在 WSL 用 `ss -ltnp '( sport = :13306 or sport = :16379 )'` 检查，也需检查 Windows 侧监听。先识别占用服务，再决定停止它或调整 Compose 的宿主端口及 `.env` 中所有对应 URL；继续绑定 `127.0.0.1`，不要直接映射到公网地址。
- **WSL 会话被回收**：实例停止期间，API 和依赖服务会停。保留开发会话；重新进入 WSL 后运行 `make dev-up`、`make dev-check`，再运行 `make run`。容器重启策略的边界及曾观察到的退出事件见 [06.3 记录](docs/learning/06.3-dev-services.md)。
- **拉镜像超时**：`make dev-up` 的拉取阶段可能出现 `i/o timeout`、`TLS handshake timeout` 或 `context deadline exceeded`，这时尚未进入数据库健康检查。先用 `docker version` 判断 daemon 是否可用，再用 `docker pull mysql:8.0` 或 `docker pull redis:7` 单独复现；不要把客户端 curl 可达等同于 daemon 可达。只读核对 daemon 的有效配置，区分连接超时与凭据/限流错误；registry 返回 401 是认证入口的正常响应。不要自行更换代理、DNS 或镜像源；环境结论见 [ADR-016](docs/adr/ADR-016-wsl-development-environment.md)。
- **数据库登录失败**：先检查 `.env` 与连接 URL 是否一致。已有数据卷时，修改初始化密码变量不会改掉库内密码；不要为了重试随意删卷。

## 文档入口

- [设计与里程碑](docs/project-design.md)
- [协作约定](docs/ai-workflow.md) 与 [仓库规则](AGENTS.md)
- [学习记录](docs/learning/) 与 [验证记录](docs/evidence/06.4-local-checks.md)
- [三层记录工作流](tech-doc-workflow/SKILL.md)
