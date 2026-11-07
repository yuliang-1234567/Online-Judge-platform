# M1 隔离集成验证准备（2026-11-07）

> 状态：m1-access 7/7、m1-problems 14/14 实库通过；后者待复核。开发库对照与资源清理通过，学习待掌握。

目标是在隔离资源上验证管理员/RBAC，以及题库/测试点的真实事务。
验收为功能往返与约束成立、并发和回滚有实证、按归属清理且开发库不变。

## 实现与入口

- AI 扩展 tools/auth_integration.py 的 --suite auth|m1-access|m1-problems。无参数保持 auth，固定选择原 test_auth.py 八项，默认 pytest 继续排除集成目录。
- m1-access 选择 test_admin_and_audit.py 七项，验证真实管理员命令、同名及大小写碰撞、两种顺序的最后管理员保护、审计/提交前故障回滚，以及同 token 立即观察角色和状态。
- m1-problems 选择 test_problem_lifecycle.py 十四项，验证生命周期、公开样例白名单、排序规则冲突、真实标签外键失效、50/51 点、父锁下发布与编辑、在途拒绝、故障回滚及 SET NULL。
- 共享 m1_support.py 只承担真实应用装配、命令子进程与有界并发时序。fixture 每用例结束仅停用本用例创建的管理员，保留用户/审计行。整轮清理由原受控入口核归属后处理。
- 应用账号按表授 DML，audit_logs 仅 SELECT/INSERT，owner 仅 SELECT。管理和迁移凭据保持原隔离，pytest 子进程严格四键；管理员命令后代只接收应用 DATABASE_URL、随机 OJ_ADMIN_PASSWORD 和禁止字节码标志，继承 pytest 进程组。
- 报告包含 suite。认证证据保留 runtime/07.5b/<run_id>/，M1 写 runtime/m1/<suite>/<run_id>/。失败、中断、先留证后核归属清理沿用现有路径。范围与调用链见 [认证模块](../modules/auth.md)。

## 离线验证

在 backend/ 以锁定的离线环境执行，pytest 的 TMPDIR 指向私有 local-reference/runtime。

| 命令 | 结果 |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 uv run --locked --offline --no-sync pytest -q -p no:cacheprovider` | 777 passed in 12.49s，退出 0 |
| `uv run --locked --offline --no-sync ruff check --no-cache .` | All checks passed!，退出 0 |
| `uv run --locked --offline --no-sync ruff format --check --no-cache .` | 70 files already formatted，退出 0 |

新增 26 项离线回归检查 suite 解析、精确表授权、子进程四键与命令后代凭据、证据路径和报告、默认收集排除。收集检查仅在无网络子进程使用归属替身放行 collect-only，取得 auth=8、m1-access=7、m1-problems=14。实际入口的服务端门禁保留。三组集成场景的本轮实跑成绩待取得。

定向入口回归曾为 140 passed，随后默认集为 776 passed。初版 Ruff 报格式、未用导入和行长，修正后新增一条命令后代环境回归，最终以表内三检查为准。

## 未验边界与运行停点

- 本轮实施停在离线复核，尚无 M1 run_id、实库报告或清理证据。真实运行先单独确认 m1-access，结束后再复核 m1-problems 的运行范围。
- QUEUED/RUNNING 与历史 submission_cases 均为隔离库手工造数，非提交端到端。实际提交接收、限制快照及历史提交可见性仍待 M2。
- 并发用例在第一笔持有真实锁后启动第二笔，有界等待并要求明确业务响应；死锁、SQL 超时或任务超时均判失败。
- 提交故障注入在 SQLAlchemy before_commit、COMMIT 发出之前，前面的 SQL/flush 在实际事务中执行。提交应答丢失和网络故障恢复仍待后续验证。
- Nginx 请求体保护仍未验，应用层大小限制沿用既有离线证据。MVP 状态见 [验收进度](../evidence/mvp-acceptance-2026-11-08.md)。

## 学习与 AI 使用

AI 起草入口扩展、测试与记录。待用户独立说明按表授权、管理员命令环境、集合锁/父锁的真实验证方法及事务故障边界。理解检查和独立复现待完成，学习待掌握。既有私有练习包保持冻结，答案保留原位置。

## m1-access 首次获准实跑（2026-11-07）

- 用户批准一次后，从 backend/ 执行 `PYTHONDONTWRITEBYTECODE=1 uv run --locked --offline --no-sync python -B tools/auth_integration.py --suite m1-access`。入口退出 65，阶段为 PREFLIGHT，错误类型 RunnerError；七项用例尚未执行。
- run_id 为 `5e0dd5006f1f44b88235530ba79c7b85`，脱敏报告位于私有 `local-reference/runtime/m1/m1-access/5e0dd5006f1f44b88235530ba79c7b85/report.json`。此结果更新上文运行前的“尚无 run_id”快照。
- 只读核对发现 MySQL 状态 running，但 NetworkSettings.Ports={}、NetworkSettings.Networks={}，HostConfig 仍记录 127.0.0.1:13306 的预期映射；docker port 无输出，ss 未发现该监听。oj-dev_default 仅挂接 Redis，Redis /16379 发布正常。
- 容器快照检查发生在建立管理连接之前，本轮尚未连接 MySQL/Redis，未创建隔离库、测试账号或前缀键；因此无本轮资源需要清理。开发库快照、迁移结构、测试结果及实资源残留核对均未进入，不能记为通过。
- 原单次运行授权已执行，MySQL 网络/端口修复和再次实跑须另行确认。m1-problems 仍待独立授权。

## m1-access 修复后实测与授权收敛（2026-11-07）

- 用户批准恢复网络并重跑一次。restart 命令退出 0，健康恢复后网络仍为空；按批准回退仅重建 MySQL，保留原命名卷。重建后网络为 oj-dev_default / 172.18.0.3，13306 监听与协议首包 0x0a 通过，Redis ID 保持原值。
- m1-access 的 run_id 为 `0a761c8e3aa74bd095e0d3aa0faff530`，入口退出 0，tests 为 passed=7、failed=0、error=0、skipped=0，cleanup_errors=[]、隔离库/两账号均 0、redis_remaining=0、development_unchanged=true，复核方确认本轮证据成立。该旧报告缺独立的开发库前后快照及 containers_after，本轮扩展报告后由新运行取得实际字段，旧报告保留。
- 造在途数据需应用会话插入，仅 m1-problems 放宽，auth suite 不变。本轮进一步收敛为 submissions 仅 SELECT/INSERT/UPDATE，submission_cases 仅 SELECT/INSERT。用例的显式 DELETE 只涉及 tags 和 test_cases，其余表授权沿用原范围。若真实执行需要额外权限，失败后停止并报告。
- 新报告写 development_before/after（table_count 与 alembic_version）及 containers_after。alembic_version 的 null 表示版本表不存在，[] 表示存在但无版本行，其他数组保留实际 version_num。development_unchanged 由前后实际值比较，采集不到时为 null。 开发库 oj 自始至终未执行迁移，因此 development_before/after 的 table_count=0、alembic_version=null 是预期基线，不是采集失败。若表数非零或出现版本值，才是偏离该基线的异常。

## 五段时间预算与实测口径

- **基线**：计划 30 秒内完成当前容器、端口、卷及工作区只读核对。本轮只读核对实测 0.214 秒；开发库 SQL 快照包含在入口运行内。上轮基线未独立计时。
- **restart**：计划命令完成后最多等 60 秒健康，间隔 2 秒。本轮基线连接性正常，无需执行；上轮命令与健康轮询的工具等待耗时为 9.67 秒。
- **重建**：仅连接性故障时考虑，健康等待预算 180 秒。本轮基线连接性正常，无需执行；上轮命令工具等待耗时为 9.22 秒，Compose 子命令记录 0、外层工具记录 1，随后独立核验全绿。
- **入口运行**：计划约 240 秒内，测试子进程保持原 180 秒硬限。本轮 m1-problems 的整条命令实测 14.906 秒，包含迁移、测试与收尾；上轮 m1-access 未独立记录整段起止时间。
- **收尾**：计划约 30 秒，按已有进程组回收与归属清理执行。本轮以末次 M1_TESTS/FAILURE 事件到 FINAL 事件的观测间隔计时，实测 0.278 秒，该值为事件观测间隔；上轮未独立计时。


新增报告回归初次将收尾原因码 65 误作进程退出码，出现 3 项断言失败。既有契约为收尾失败退出 70、finalization_error 保存原因码 65；修正新增断言后定向 148 passed in 4.52s，退出 0。


## 收敛授权后的 m1-problems 实测（2026-11-07）

- 本轮三检查在 backend/ 执行，均退出 0。默认 pytest 为 784 passed in 12.10s，Ruff 为 All checks passed!，格式为 70 files already formatted。相对初版新增七项快照及容器回归。
- 运行起止为 `2026-11-07T16:25:50.706612+08:00` 至 `2026-11-07T16:26:05.612226+08:00`，命令为 `PYTHONDONTWRITEBYTECODE=1 uv run --locked --offline --no-sync python -B tools/auth_integration.py --suite m1-problems`。仅运行一次，入口退出 0。
- run_id=`07a40887c9bf447ca106616da1cd6b50`，tests 为 passed=14、failed=0、error=0、skipped=0、failed_tests=[]。submissions 无 DELETE、submission_cases 无 UPDATE/DELETE 的授权下通过，未放宽权限。
- development_before 与 development_after 均为 `{"table_count": 0, "alembic_version": null}`，两者比较得到 development_unchanged=true。MySQL ID 前后均为 `c7f65b2ad8186ffe997af6bf95d5cae89ba6fbc8b94d4b29fabaf5eb809326f7`，Redis ID 前后均为 `220df8eece9063c8633b64589fe17e67bd1dad843221c2f41bb997207289f361`。
- cleanup_errors=[]，inventory_after 中隔离库与两账号均为 0，redis_remaining=0。证据为私有 `local-reference/runtime/m1/m1-problems/07a40887c9bf447ca106616da1cd6b50/report.json`。本轮无 restart/重建，未重跑用例。
- 该成绩覆盖本节十四项场景。QUEUED/RUNNING 与历史明细为手工造数，M2 提交端到端、提交应答丢失、Nginx 和个人理解验收继续待完成。
