# OJ 在线判题系统

Python 后端求职项目，目标是实现题库、异步判题与结果查询。需求以 [项目设计](docs/project-design.md) 为准。

## 当前进度

| 编号 | 这一节做什么 | 状态 | 对应提交 |
| --- | --- | --- | --- |
| 06.1 | 仓库规则、换行约定、环境变量模板 | 已完成 | b34da9e / c7738ce |
| 06.2 | 后端骨架：uv、Ruff、pytest、/healthz | 已完成 | f71c890 / b52f128 |
| 06.3 | MySQL 与 Redis 开发服务、Makefile | 已完成 | 4ecde79 |
| 06.4 | pre-commit、最小 CI、README | 已完成 | f27c93e / 6099783 |
| 06.5 | 判题环境探针（Docker 文件与权限链路） | 本地验收通过 | dd32e92 |
| 07.1 | 数据库表清单与 ER 对照核对（设计 §9，M1 前置） | 已完成 | 4e7df7f / b894d0b |
| 07.2 | 按 12 项数据库决策更新设计 §9 与 ER 图 | 已完成 | 5e7ccb6 |
| 07.3 | 三张文字表的建表语句与索引落定 | 已完成 | fa35097 |
| 07.4 | 首版九表迁移与离线结构验证 | 离线通过；实库往返见 07.4b | 8e74434 / 9c7a7ef |
| 07.4b | MySQL 8 隔离库升级→回退→再升级与结构核对 | 已验证并清理；开发库验证时未迁移 | 7a6c0c0（记录；验证基线 e55637a） |
| 07.5a | 注册、登录与当前用户鉴权；离线验证及学习材料 | 离线验证通过；实库验证见 07.5b | 5009830 / 6675be6 |
| 07.5b | 认证隔离 MySQL/Redis 集成、UTC 与生命周期验证 | 离线 306 passed、集成 8 项通过（run_id 6df187da）；已复核；学习待掌握 | 89dd044 / 7abab72（自测题 8dcd621） |
| 07.6 | 一次性初始管理员命令与私有练习包 | 默认 353 passed；命令离线 47 项通过；实库未验证；学习待掌握 | 已提交：126a06c / 709aade |
| 07.7 | 用户权限管理、最后管理员保护与原子审计 | 离线通过；实库并发待验；学习待掌握 | 已提交：91a0071 / 7438f0a |
| 07.8 | 题目草稿、标签、原子审计与请求体限制 | 离线 566 passed，用户 filled 147/147；实库/Nginx 未验；学习待掌握 | 已提交：c358c77 / 6bb6cea |
| 07.9 | 测试点管理与在途编辑保护 | 离线 710 passed，实库/Nginx 待验，学习待掌握 | 未提交 |

1. 日期依据是 [设计文档 §17.2「重排执行表」](docs/project-design.md#172-重排执行表)；06.5 对应其中「阶段06末尾，限半天」那一行。
2. 06.x 是阶段06内部的施工编号，设计文档没有这一层编号。07.x 是阶段07内部的施工编号，设计文档同样没有这一层编号。
3. 06.1—06.3 于 2026-10-19 完成，早于 §17.2 的计划窗口，原因是 Docker 网络问题未阻塞主线；如实记录，不为了对齐计划表而改日期。
4. 表中哈希在下一个记录类提交回填；一个提交无法包含自身哈希。

当前已实现 `GET /healthz`、`POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`GET /api/v1/auth/me`；认证已通过离线验证及本地隔离 MySQL/Redis 集成验证（07.5b，已复核并提交）。题目草稿、标签与测试点管理已离线实现。发布/下线、公开查询与判题留给后续小节。提交的是 AI 起草源码，用户练习未回移；学习待掌握与代码已交付分别记录，见 [练习包流程](.agents/skills/practice-drill-workflow/SKILL.md)。

07.7 已实现 `GET /api/v1/admin/users`、`PATCH /api/v1/admin/users/{id}`、`GET /api/v1/admin/audit-logs`；当前离线通过，真实 InnoDB 并发与回滚待验，学习待掌握。入口与边界见 [管理模块](docs/modules/admin.md)及 [07.7 学习记录](docs/learning/07.7-admin-users.md)。

07.8 实现管理员题目四接口与标签两接口，当时仅 DRAFT 可编辑。题目、标签关联与审计共同提交，写入口按实际接收字节限制请求体。2026-11-05 执行方在 backend/ 实测 `PYTHONDONTWRITEBYTECODE=1 uv run --locked --offline --no-sync pytest -q -p no:cacheprovider` 为 566 passed in 7.28s，Ruff/格式检查均退出 0；私有包 reference 147/147 和 initial 16 项预期红属于生成验收，不是用户成绩。真实 MySQL 并发、持久化回滚、排序规则与 Nginx 未验，学习待掌握；见 [题目模块](docs/modules/problem.md)和 [07.8 学习记录](docs/learning/07.8-problem-draft.md)。

07.9 增加测试点管理四接口。DRAFT/OFFLINE 可写，存在在途提交时拒绝测试点写入和实际限制变化。真实锁、回滚及部署验证待做。见 [测试点模块](docs/modules/test_case.md)与 [07.9 学习记录](docs/learning/07.9-test-cases.md)。

`/healthz` 返回 `200` 和 `{"status":"ok"}`，只检查进程存活；应用缺有效认证配置时启动失败，`/healthz` 也不可用。API 启动和存活检查不会建表或验证依赖可用。

首版迁移已在 MySQL 8.0.46 隔离库完成升级→回退→再升级与结构核对并清理；这些验证没有迁移开发库。新建开发库需手动执行下文迁移才能使用认证接口；当前没有演示账号。MySQL/Redis 是本地开发依赖，API 在 WSL 本地运行。

07.4 主本 `8e74434` 与记录 `9c7a7ef` 已于 2026-10-23 推送。07.4b 记录 `7a6c0c0`、07.5a 主本 `5009830` 与记录 `6675be6`、练习协作规则 `87cd540` 均已发布；2026-11-01 API 核验 GitHub main 为 `87cd540`。

2026-11-01T14:45:22+08:00 通过 [GitHub Actions API](https://api.github.com/repos/yuliang-1234567/Online-Judge-platform/actions/runs?branch=main&per_page=100) 核验 main 分支：按 run ID 去重，重跑 attempt 不另计，共 31 次（与 total_count 一致），30 success、1 cancelled、0 failure、0 未完成。最近 [run 41281465672](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/41281465672) 为 completed / success，对应 `87cd540`。这是该时点的远端快照，不包含本次 README 修改；默认 CI 不含隔离库集成和私有练习节点。

<details>
<summary>历史 CI 快照（保留原统计时间）</summary>

2026-11-01T13:43:18+08:00 本次推送前通过 [GitHub Actions API](https://api.github.com/repos/yuliang-1234567/Online-Judge-platform/actions/runs?branch=main&per_page=100) 核验 main 分支：按 run ID 去重、重跑 attempt 不另计，共 29 次（与 total_count 一致），28 success、1 cancelled、0 failure、0 未完成。最近 [run 40200558263](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/40200558263) 为 completed / success，对应 9c774a6；此快照不计本次 07.5a 推送后新产生的运行。默认 CI 不含隔离库集成和私有练习节点。

历史快照（保留统计时间）：2026-10-25T17:00:19+08:00 通过 [GitHub Actions API](https://api.github.com/repos/yuliang-1234567/Online-Judge-platform/actions/runs?branch=main&per_page=100) 核验：按 main 分支的 workflow run ID 去重计数，重跑 attempt 不另计；本页返回 27 条，与 total_count 一致，共 27 次，其中 26 次 `success`、1 次 `cancelled`、0 次 `failure`、0 次未完成。最近一次 [run 40093329331](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/40093329331) 为 `completed / success`，对应提交 `e55637a`，工作流 `Backend checks`。重复触发的成因仍记在 [待确认清单](docs/learning/open-questions.md)。当前工作流仅覆盖后端 Ruff 与已有 pytest 用例，不包含本轮手工隔离库往返验证。

</details>

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

复制只做一次；已有 `deploy/.env` 时保留原配置，不覆盖。用编辑器填写 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`REDIS_PASSWORD`，三者使用不同的本地密码。可分别运行 `python3 -c 'import secrets; print(secrets.token_hex(32))'` 生成不含 URL 特殊字符的值。保留模板中的数据库名和用户名；把连接 URL 中的 `REPLACE_ME` 分别替换成对应密码。`JWT_SECRET` 另行生成填写（至少 32 字节）。应用在启动阶段校验配置；缺少有效密钥或连接 URL 时启动失败，`/healthz` 也不可用。启动成功后的存活检查不连接 MySQL 或 Redis。真实 `.env` 已被 Git 忽略，不要提交。

```bash
make install
uv run --project backend --locked pre-commit install
uv run --project backend --locked pre-commit run --all-files
make dev-up
make dev-check
make test
make lint
```

`make install` 按锁文件安装依赖；`make dev-up` 只启动 MySQL/Redis 并等待健康检查。`make dev-check` 应依次得到 `mysqld is alive`、查询结果 `1`、`PONG`。默认只运行非 docker 标记的用例，探针用显式入口。

### 使用认证接口前：准备业务表

`make dev-up` 在新数据卷中初始化数据库和账号，不创建业务表；`make dev-check` 也不运行迁移。仅检查 `/healthz` 无需建表，注册/登录/me 则需要已有 `users` 表。

下面命令会连接并修改 `DATABASE_URL_SYNC` 指向的数据库。执行前在本地确认它与 `DATABASE_URL` 指向同一开发库（模板为 `127.0.0.1:13306/oj`，账号 `oj_app`），不要打印连接串。已有数据库先核对版本；若已有业务表但没有对应迁移记录，停止核对，不用删卷或 `stamp` 绕过。

```bash
(cd backend && uv run --locked --offline --env-file ../deploy/.env alembic -c alembic.ini current)
(cd backend && uv run --locked --offline --env-file ../deploy/.env alembic -c alembic.ini upgrade head)
```

迁移显式使用同步 `mysql+pymysql` 连接；应用使用异步 `mysql+asyncmy` 连接。首次迁移应创建九张业务表及 `alembic_version`，当前版本为 `0001_initial_schema`。这是开发操作说明，07.5a 的认证实库集成仍未验收。

### 启动 API

```bash
(cd backend && uv run --locked --offline uvicorn app.main:app --env-file ../deploy/.env)
```

上面的 `uvicorn --env-file` 命令显式读取 `deploy/.env` 并在前台启动 API；仅填写文件不会自动注入进程环境。保留该终端；另开一个 WSL 终端执行：

```bash
curl --fail --show-error http://127.0.0.1:8000/healthz
```

预期响应 `{"status":"ok"}`。Swagger 地址为 `http://127.0.0.1:8000/docs`。用 Ctrl+C 停止 API；`make dev-down` 停止依赖服务并保留数据卷。

### 认证接口快速检查

先完成业务表迁移并保持 MySQL/Redis 可用，再在 Swagger 中操作：

1. `POST /api/v1/auth/register`：填写 `username`、`password`；用户名为 3–32 个 ASCII 字母、数字或下划线，注册密码为 15–128 Unicode 码点且不能全为空白。成功返回 `201`，注册只创建普通用户。
2. `POST /api/v1/auth/login`：使用刚注册的凭据，成功返回 `200`；从响应取得 `access_token`。
3. 点击 Swagger 的 **Authorize**，填入 token 本身，不加引号或重复的 `Bearer ` 前缀；再执行 `GET /api/v1/auth/me`，应返回当前用户公开信息，不含 `password_hash`。

这些操作会真实访问依赖并可能写入用户或限流数据，不属于默认 pytest。错误码、输入约束及验证边界见 [认证模块文档](docs/modules/auth.md)；接口可用不代表用户已通过理解验收。

## 创建初始管理员（07.6）

先完成开发库迁移，并在本地确认 `deploy/.env` 的 `DATABASE_URL` 指向预期库。以下命令会真实写入该库的 users 表，不属于默认 pytest；本节当前只做离线验证，没有执行此写库命令。

```bash
(cd backend && uv run --locked --offline --env-file ../deploy/.env python -B -m tools.create_admin --username admin)
```

默认在终端隐藏输入密码两次确认，规则与注册一致。只有非交互运行才使用 `OJ_ADMIN_PASSWORD`，由安全环境注入；把真实值直接写进 shell 赋值命令可能留在历史中，不在命令行参数中传密码。命令只创建 ADMIN/ACTIVE，不会提升、覆盖或重置已有账号；成功后可用现有登录接口登录。失败与中断须先只读核查账号状态，不自动重试。`--help` 不读配置、不连库。退出码和学习状态见 [07.6 记录](docs/learning/07.6-create-admin.md)；学习待掌握。

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

## 认证隔离集成验证（07.5b）

默认 pytest/CI 排除认证集成目录。显式运行前需本地 MySQL/Redis 已就绪、deploy/.env 有效且后端依赖已同步；在 backend/ 执行：

```bash
uv run --locked --offline --no-sync python -B tools/auth_integration.py
```

该命令会创建 oj_auth_check、独立应用/迁移账号，迁移并运行八项实库测试，再按归属清理。Redis 使用共享开发实例的 /4 和本轮 run_id 前缀；不迁移开发库，不开放 --clear、恢复子命令或 FLUSHDB。失败/中断先停进程、留证，再清理归属匹配的资源；归属不明或留证失败则保留。证据 run_id 为 6df187da8e63476b91e6084c24e43c4a。

本地证据覆盖真实认证、大小写并发冲突、事务回滚、状态/角色重读、Lua/TTL、限流、连接池恢复及 UTC。HTTP 经过进程内 ASGI，尚不代表公网链路、压测或 M1 整体验收。结果和边界见 [07.5b 学习记录](docs/learning/07.5b-auth-integration.md)；脱敏运行报告存于私有 local-reference/runtime/07.5b/<run_id>/。

## Worker 环境探针（06.5）

在 WSL 仓库根目录执行，前提是已同步后端依赖，本地已有官方 python:3.12-slim，普通用户可访问原生 Docker daemon：

```bash
uv run --project backend --locked --offline python backend/tools/worker_probe.py build
make probe
```

构建只复制探针脚本，不安装依赖，不主动拉取镜像；缺少本地基础镜像会失败。make probe 复用已构建的镜像，底层显式传入 -o addopts="" -m docker。
默认 pytest 的 Docker 目录在收集前被忽略；显式运行选中 success、failure、timeout 三个场景，缺 Docker 或探针镜像时应失败，不以 skip 代替验收。

每个场景生成独立随机标记、两个一次性容器和临时目录；正常、退出 23、SIGKILL 退出 137 均验证文件内容、身份及清理。脚本保留实际退出码，pytest 仅在预期退出与清理断言全部成立时返回成功。
容器统一使用当前 UID:GID、none 网络、禁止拉取、只读根文件系统与 /tmp tmpfs。验收清理容器和临时目录，探针镜像保留供重跑。
本节限时半天，非预期失败时清理并记录后停止，不阻塞认证切片。实测证据和适用边界见 [06.5 记录](docs/learning/06.5-worker-probe.md) 与 [ADR-016](docs/adr/ADR-016-wsl-development-environment.md)。

## 排障

- **缺少配置**：`make dev-up` 在缺 `deploy/.env` 时输出中文提示并失败；它不替 API 注入环境。API 报“认证配置错误”时，检查配置是否填写完整，并使用上面的显式 env-file 启动命令。不要用忽略错误的方式绕过失败。
- **13306/16379 被占用**：Compose 会报告端口无法绑定。在 WSL 用 `ss -ltnp '( sport = :13306 or sport = :16379 )'` 检查，也需检查 Windows 侧监听。先识别占用服务，再决定停止它或调整 Compose 的宿主端口及 `.env` 中所有对应 URL；继续绑定 `127.0.0.1`，不要直接映射到公网地址。
- **WSL 会话被回收**：实例停止期间，API 和依赖服务会停。保留开发会话；重新进入 WSL 后运行 `make dev-up`、`make dev-check`，再从仓库根执行 `(cd backend && uv run --locked --offline uvicorn app.main:app --env-file ../deploy/.env)`。已有数据卷不需要为重启重复初始化。容器重启策略的边界及曾观察到的退出事件见 [06.3 记录](docs/learning/06.3-dev-services.md)。
- **拉镜像超时**：`make dev-up` 的拉取阶段可能出现 `i/o timeout`、`TLS handshake timeout` 或 `context deadline exceeded`，这时尚未进入数据库健康检查。先用 `docker version` 判断 daemon 是否可用，再用 `docker pull mysql:8.0` 或 `docker pull redis:7` 单独复现；不要把客户端 curl 可达等同于 daemon 可达。只读核对 daemon 的有效配置，区分连接超时与凭据/限流错误；registry 返回 401 是认证入口的正常响应。不要自行更换代理、DNS 或镜像源；环境结论见 [ADR-016](docs/adr/ADR-016-wsl-development-environment.md)。
- **数据库登录失败**：先检查 `.env` 与连接 URL 是否一致。已有数据卷时，修改初始化密码变量不会改掉库内密码；不要为了重试随意删卷。

## 文档入口

- [设计与里程碑](docs/project-design.md)
- [协作约定](docs/ai-workflow.md) 与 [仓库规则](AGENTS.md)
- [学习记录](docs/learning/) 与 [验证记录](docs/evidence/06.4-local-checks.md)、[数据库表与 ER 核对](docs/evidence/db-schema-check.md)
- [认证模块与错误边界](docs/modules/auth.md) 与 [Worker 探针模块](docs/modules/worker-probe.md)
- [练习包流程：不剥离、不回移，交付与学习分开](.agents/skills/practice-drill-workflow/SKILL.md)
- [三层记录工作流](.agents/skills/tech-doc-workflow/SKILL.md)
- [每轮风险拍板点规则](.agents/skills/risk-checkpoint/SKILL.md)
