# 认证模块（07.5a / 07.5b）

## 职责
提供注册、登录和当前身份查询，按请求读取账号状态与角色；不实现 refresh、吊销黑名单、找回密码或管理员创建。接口契约见 [设计 §11.2](../project-design.md#112-认证接口)（D:1126–1132）。

## 涉及文件
| 文件（相对仓库根） | 作用 |
| --- | --- |
| `backend/app/main.py`、`backend/app/core/config.py`、`backend/app/core/db.py` | 控制启动校验、惰性资源及请求会话 |
| `backend/app/core/security.py`、`backend/app/core/rate_limit.py`、`backend/app/core/http.py` | 密码/JWT、配额及安全错误边界 |
| `backend/app/api/v1/auth.py`、`backend/app/api/deps.py` | 对外契约与身份/权限依赖 |
| `backend/app/models/user.py`、`backend/app/models/base.py`、`backend/app/schemas/auth.py` | 既有 users 映射、公共响应与输入校验 |
| `backend/app/repositories/user.py`、`backend/app/services/auth.py` | 查询细节与认证事务编排 |
| `backend/tests/unit/test_security.py`、`backend/tests/unit/test_auth_service.py`、`backend/tests/unit/test_auth_rate_limit.py`、`backend/tests/unit/test_auth_startup.py` | 机制与故障分支 |
| `backend/tests/api/test_auth.py`、`backend/tests/api/test_healthz.py` | 真实 HTTP 接线与无连接启动 |
| `backend/tools/auth_integration.py`、`backend/tests/integration/conftest.py`、`backend/tests/integration/test_auth.py` | 受控隔离资源生命周期、双 owner 门禁及真实认证场景 |
| `deploy/.env.example`、`backend/pyproject.toml`、`backend/uv.lock` | 配置入口与固定依赖；不读取真实凭据作测试 |

## 调用链
1. `uvicorn app.main:app` 导入只建路由；lifespan 才构造 Settings、惰性 MySQL/Redis 客户端和每实例密码上下文。
2. register：输入校验 → IP 配额 → 线程池哈希 → 短事务内 INSERT/flush/refresh/commit → 公开用户响应。
3. login：格式校验/归一化失败键 → 短事务查用户 → 真哈希或 dummy 校验 → 失败计数或签发 JWT。
4. me/权限依赖：验证 token → 以 sub 重新查用户 → 禁用/角色判断 → 响应；请求结束关闭 session。

## 关键决策
- 用户名 ASCII 3–32（不支持中文），大小写唯一性由既有排序规则负责；密码按 Unicode 码点计数，注册 15–128，不 trim/规范化，避免悄悄改变凭据。见 D:1126–1127、1296。
- Argon2id 在线程池执行；真实与 dummy 共用每应用实例 CapacityLimiter(2)，满额 429 + Retry-After: 1。取消要等实际线程结束才还名额，防止断连绕过并发上限。见 D:235–236、1029。
- 未知用户仍做 dummy 校验，不能从“少一次哈希”枚举账号；不声称端到端恒定时间。损坏哈希仅将 InvalidHashError 明确映射 500；VerifyMismatchError 保持错误凭据 401。见 D:1300。
- JWT 固定 HS256；SecretStr 只局部解包。sub 用 `re.fullmatch(r"[1-9][0-9]*", value)`，转 int 前限 20 位，再卡 BIGINT UNSIGNED 上界；不能用带 $ 的 match 让尾随换行漏过。见 D:1297。
- 已核 PyJWT 2.15.1 的时间校验会 int() 强转；返回的原始 payload 仍须 `type(x) is int` 检查 iat/exp，拒绝 bool/float/字符串。见 D:1297。
- 唯一约束处理并发重名；仅 MySQL 1062 且 uk_users_username 转 409，其余错误不能冒充重名。哈希在事务外，写入与提交失败均回滚。沿用 users，未新增迁移。见 D:715–724。
- Lua 把计数与首次 TTL 写成一次原子调用，防止中断留下永久键；登录先查再记失败，在途并发不承诺严格五次总量，跨用户名也不承诺 IP 总限速。见 D:1025、1035–1036。
- Redis 同时是 broker，故障期注册暂停并返回 503；登录限流故障放行并只记固定告警。限流键使用 RATE_LIMIT_KEY_PREFIX，用户名先验格式再小写，身份摘要不明文存入键。见 D:1031、1035。
- token 不保存角色/状态；每次查库才能让禁用或降权在下一次请求生效。统一错误体不回传密码输入、哈希或原异常，日志不记录 Authorization/token。见 D:1299、1336。

## 异常与边界
- 401 使用 UNAUTHENTICATED；重复用户名 409/CONFLICT；禁用/无权限 403/FORBIDDEN；422 仅固定字段提示；429 带重试秒数，数据库 OperationalError/连接池 TimeoutError 返回 503；未识别的程序错误保留 500。见 D:1113–1120。
- JWT_SECRET 缺失或不足 32 字节时启动报“认证配置错误”，/healthz 也不可用；启动成功不等于依赖可用。测试注入占位 Settings，不依赖环境里的真实凭据。
- 生产在 backend/ 用 `uv run --locked --offline uvicorn app.main:app --env-file ../deploy/.env` 显式加载配置；模块级 app 不读取 AUTH_INTEGRATION_*。
- 07.5b 已实测 MySQL 大小写并发冲突、事务回滚、账号状态/角色重读、asyncmy/PyMySQL 握手、真实应用池排队/超时/恢复、Redis Lua/TTL 及应用/迁移实际连接 UTC；证据范围见 [学习草稿](../learning/07.5b-auth-integration.md)。HTTP 使用进程内 ASGI，不代表公网链路或压测通过。
- 管理连接在 autocommit 下显式 SET 会话 UTC，并在建库前回读、单独记录 management_session_tz；默认会话使用另一独立连接核验，不能用 SET 后的值代替。应用与 Alembic 沿用各自连接初始化。迁移内联探针只用 DBAPI cursor 读取时区并立即 rollback，不改 Alembic 环境文件；缺少实际 UTC 结果不算通过。
- 集成入口只管理 oj_auth_check、独立应用/迁移账号和 Redis /4 本轮前缀；/4 与开发共享实例。账号 host 来自服务端实测来源，不由回环发布地址推断。不开放 --clear、恢复子命令、FLUSHDB 或生产测试路由。
- 失败/中断先停进程、持久化脱敏证据，再分别验证 MySQL owner/账号 ATTRIBUTE 和 Redis owner 后清理；证据失败或归属不明则保留，人工恢复另批。SIGINT/SIGTERM 实库演练已核退出码、进程组及残留；不承诺 SIGKILL/断电自动清理。

## 怎么测
在 `backend/` 执行（均离线，不启动服务、不连库）：
```bash
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
uv run --locked --offline pytest -q
```
默认测试覆盖真实 Argon2/JWT、合成事务/Redis、独立 app 的权限依赖及禁用/降权；数据库故障回归经过真实路由/服务/会话依赖，以内存会话验证 503/500、脱敏与清理调用，不能证明实库回滚。默认排除 Docker 与认证集成。
取消测试用线程事件确认资源责任；日志断言同时检查固定事件存在与敏感原文缺失，避免“根本没记录”假绿。真实数据库和 Redis 验收属于另一层证据。

实库受控入口（在 backend/；会建库、迁移、测试并按归属清理）：
```bash
uv run --locked --offline --no-sync python -B tools/auth_integration.py
```
无参数执行完整流程，默认 pytest 不会进入该流程。root 凭据只由入口读取 deploy/.env；测试子进程只收到四项集成配置，fixture 不读真实 .env。脱敏报告位于私有 local-reference/runtime/07.5b/<run_id>/report.json。
