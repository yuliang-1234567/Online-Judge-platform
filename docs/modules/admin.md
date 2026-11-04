# 用户权限管理与审计（07.7）

## 1 职责

提供管理员用户列表、角色/状态修改与审计查询；接口与锁协议见 [设计 §11.6](../project-design.md#116-管理接口apiv1admin)。不提供角色表、通用权限框架或 JWT 角色缓存。

## 2 涉及文件

| 文件（相对仓库根） | 作用 |
| --- | --- |
| `backend/app/api/v1/admin.py`、`backend/app/api/deps.py`、`backend/app/main.py` | 路由、统一管理员鉴权与注入 |
| `backend/app/schemas/admin.py`、`backend/app/core/http.py` | 输入/响应白名单与安全错误 |
| `backend/app/repositories/user.py`、`backend/app/services/admin.py` | 当前值锁定、保护与事务编排 |
| `backend/app/models/audit_log.py`、`backend/app/repositories/audit_log.py` | 既有审计表映射、追加及游标查询 |
| `backend/tests/unit/test_admin_service.py`、`backend/tests/api/test_admin_user.py` | 离线协议、故障与 HTTP 契约 |

## 3 调用链

1. 管理 APIRouter 统一调用 require_admin；JWT 鉴权逐请求查当前角色和状态，PATCH 复用同一依赖结果。
2. 用户列表用 page/size（size≤50）及用户名子串搜索；审计用 cursor/limit（limit≤100），末页 next_cursor=null。
3. PATCH DTO 仅收 role/status，拒绝空对象、显式 null、未知字段与非法值。
4. AdminService 在事务内执行保护、锁目标、更新及审计；仓储只 flush，不 commit。
5. 响应从 schema 白名单生成；事务成功退出才返回，故障统一走安全错误处理。

## 4 关键决策

- 减少有效管理员的更新先按 id 升序锁 ADMIN/ACTIVE 集合，再锁目标；只锁不同目标行不能保护跨行不变量。目标锁定读刷新 identity map，避免鉴权旧值。
- 新建管理员、纯晋升、纯激活不主动取集合保护锁；混合降权/禁用仍进入保护路径。真实物理锁范围不由此承诺。
- 业务修改与审计同事务：保护拒绝不写入；审计失败使已 flush 的修改一起回滚。
- 审计仅记录管理员写操作；摘要只选角色/状态前后值，生成后截至 2048 字符，不截原始请求体。
- IP 取服务器 peer 并规范化；缺失/非法值记 unknown，不直接相信 X-Forwarded-For。
- 决策依据集中于设计 §11.6 与 §9 的审计约束；本节没有新增 ADR。

## 5 未验证边界与异常

- 401：身份无效；403：普通用户或禁用账号；404：目标用户不存在；409：最后管理员保护。
- 422：输入不合法；依赖操作或连接池超时返回安全 503；其他异常返回固定 500，不回显 SQL 参数或请求体。
- 同 token 在降权后不能访问管理接口，普通 /me 仍可读取 ACTIVE 用户；禁用后 /me 返回 403。
- 并发与回滚使用事务替身，真实 InnoDB 并发、锁范围和持久化回滚尚未验收；未跑实库。
- 模型映射既有 audit_logs，不新增表结构或迁移。

## 6 离线测试

从 backend/ 运行：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked --offline --no-sync pytest -q -p no:cacheprovider
uv run --locked --offline --no-sync ruff check --no-cache .
uv run --locked --offline --no-sync ruff format --check --no-cache .
```

2026-11-03 执行结果：419 passed in 6.48s；All checks passed!；46 files already formatted，均退出 0。私有练习与学习状态见 [07.7 学习记录](../learning/07.7-admin-users.md)。
