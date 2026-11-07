# MVP 验收进度（M1 时点快照，2026-11-08）

> 预验收草案，取证日期为 2026-11-07，代码基线为 91af177。验收表待用户复核，设计附录 A 保留待勾选状态。

## 口径

附录 A（docs/project-design.md:1926）是 MVP 总验收清单，跨越 M1–M4，未完成的框保持不勾。M1 的交付标准见 §17.2 第 1782 行「RBAC、题库、测试数据管理及管理员命令」。本表记录 M1 时点各条的进度证据，不代替里程碑判定。 [MVP 附录 A](../project-design.md#附录-amvp-开发验收清单) · [M1 交付范围](../project-design.md#172-重排执行表)

下表覆盖附录 A 第 1928–1939 行中选定的七项，行号按本轮源码核对。状态取「离线通过」「部分」「未实现」「实库未验」，跨阶段缺口按所属阶段列明。正式里程碑继续按设计 §17.1 和 §17.2 复核。 [设计里程碑](../project-design.md#171-里程碑)

## 七项对照

| 设计行号 | 要求原文摘要 | 现有证据与缺口 | 状态 | 是否建议勾选 |
| --- | --- | --- | --- | --- |
| [设计:1928](../project-design.md) | 一次性管理员命令可用，密码不进入迁移、源码、参数或日志 | 07.6 命令已落地，47 项定向单测覆盖密码输入、参数拒绝、日志脱敏、事务及退出码。真实 MySQL 建号、并发重名、回滚和管理员登录往返待验。证据见 [07.6 learning:12](../learning/07.6-create-admin.md)、[07.6 learning:16](../learning/07.6-create-admin.md)、[07.6 learning:22](../learning/07.6-create-admin.md)。 | 实库未验 | 否，隔离库验证后再定。 |
| [设计:1929](../project-design.md) | 在途编辑与提交并发约束验收，限制快照保持稳定 | 07.9 编辑侧的父题目锁、在途拒绝和故障回滚有事务替身证据。M2 提交接收、限制快照写入及其与编辑并发的端到端协议当前未实现。证据见 [07.9 learning:28](../learning/07.9-test-cases.md)、[07.9 learning:29](../learning/07.9-test-cases.md)，现有应用挂载见 [main.py:57](../../backend/app/main.py)。 | 未实现 | 否，需完成 M2 提交侧和隔离库并发验收。 |
| [设计:1930](../project-design.md) | request_id 与 idempotency_key 职责分离，隐藏点 stdout/stderr 响应为白名单 | 现有 request_id 中间件和错误脱敏已实现。M2 提交幂等、判题结果及隐藏点 stdout/stderr 响应当前未实现。公开题库样例白名单已有离线证据，提交结果白名单仍待落地。证据见 [core/http.py:84](../../backend/app/core/http.py)、[core/http.py:92](../../backend/app/core/http.py)、[main.py:57](../../backend/app/main.py)。 | 未实现 | 否，需完成 M2 提交链路。 |
| [设计:1931](../project-design.md) | Worker/并发测试使用独立测试库并清表 | 07.5b 已在 oj_auth_check 隔离库完成认证并发实测，归属核验后清理隔离资源，报告残留为 0、开发库不变。Worker/判题并发的数据库测试仍待实现，认证入口的清理证据仅覆盖认证范围。证据见 [07.5b learning:13](../learning/07.5b-auth-integration.md)、[07.5b learning:14](../learning/07.5b-auth-integration.md)、[集成门禁:17](../../backend/tests/integration/conftest.py)。 | 部分 | 否，补 Worker/提交并发的隔离与清理证据后再定。 |
| [设计:1935](../project-design.md) | JWT 登录、注册、RBAC 可用，角色与状态不缓存，禁用/降权立即生效 | 07.5b 的 8 项真实集成含注册登录、同 token 禁用/降权/删除。当前鉴权逐请求查库。07.7 用户管理与审计已离线实现，真实 InnoDB 管理并发、最后管理员保护与持久化回滚待验。证据见 [07.5b learning:42](../learning/07.5b-auth-integration.md)、[07.5b learning:45](../learning/07.5b-auth-integration.md)、[deps.py:94](../../backend/app/api/deps.py)、[admin 模块:39](../modules/admin.md)。 | 实库未验 | 否，保留认证已实测事实，补验管理变更全链路。 |
| [设计:1937](../project-design.md) | 题库分页、题目详情、管理员 CRUD 与发布/下线可用 | 07.8–07.10 六条题目/标签管理接口、四条测试点管理接口和四条发布/公开接口已有离线实现。07.10 默认集 751 passed in 9.67s，Ruff 通过、66 files already formatted。真实 MySQL 并发、持久化回滚、排序规则及题库 API 往返待验。证据见 [README:23](../../README.md)、[README:24](../../README.md)、[README:25](../../README.md)、[07.10 learning:19](../learning/07.10-public-problems.md)、[07.10 learning:23](../learning/07.10-public-problems.md)。 | 实库未验 | 否，隔离实库往返与并发验证后再定。 |
| [设计:1939](../project-design.md) | 测试数据区分样例与隐藏，对外 DTO 不含隐藏用例 | 公开样例 DTO 只有 case_index/input_data/expected_output，嵌套白名单、SQL 的 is_sample=true 过滤和公开 API 隐藏内容检查均有离线测试。证据见 [public_problem schema:25](../../backend/app/schemas/public_problem.py)、[白名单单测:102](../../backend/tests/unit/test_problem_publication.py)、[SQL 单测:204](../../backend/tests/unit/test_problem_publication.py)、[API 测试:156](../../backend/tests/api/test_public_problem.py)，通过结果见 [07.10 learning:19](../learning/07.10-public-problems.md)。 | 离线通过 | 暂缓，现有证据支持公开题库离线契约，正式勾选待隔离实库读取复核。 |

## M1 交付核对

以下四项对应设计 §17.2 第 1782 行。三条验收按各节 learning 的已批准口径逐项核对，满足情况限定为现有离线证据。

| 交付物 | 离线证据 | 该节三条验收的满足情况 | 未验边界 |
| --- | --- | --- | --- |
| 管理员命令（07.6） | 定向单测 47 项通过，当节默认集 353 passed，Ruff 与格式通过。 [07.6 learning:21](../learning/07.6-create-admin.md) | ① 密码、配置和异常不回显，单测覆盖。② 用户名唯一键分类与事务边界，替身覆盖。③ 仓库三检查及参考/初始练习接线证据齐全。三条均有离线证据。 [07.6 验收:6](../learning/07.6-create-admin.md) · [练习接线:24](../learning/07.6-create-admin.md) | 实库建号、大小写并发、真实回滚及管理员登录往返未验。 |
| RBAC（07.7） | 当节默认集 419 passed，Ruff 与格式通过。后续合并到 07.10 的默认集为 751 passed。 [07.7 learning:22](../learning/07.7-admin-users.md) · [07.10 learning:19](../learning/07.10-public-problems.md) | ① 权限与 DTO 契约离线通过。② ADMIN/ACTIVE 集合锁先于目标锁，事务替身及 SQL 声明核对通过。③ 用户修改与审计共提交、故障共回滚，替身通过。 [07.7 验收:6](../learning/07.7-admin-users.md) · [锁协议:16](../learning/07.7-admin-users.md) | 真实 InnoDB 并发、最后管理员保护及持久化回滚未验。理解检查与独立复现待完成。 |
| 题库（07.8 + 07.10） | 07.8 默认集 566 passed，07.10 默认集 751 passed，两节 Ruff/格式通过。 [07.8 learning:17](../learning/07.8-problem-draft.md) · [07.10 learning:19](../learning/07.10-public-problems.md) | 07.8 的① 六接口权限、输入与分页、② 故障回滚和约束分类、③ 四项实际字节 413 及仓库检查均有离线证据。07.10 的① 生命周期与事务、② 发布门槛和公开 DTO 白名单、③ 仓库检查及练习包生成验收均通过。用户 filled 41/41 已记入补记。 [07.8 验收:6](../learning/07.8-problem-draft.md) · [07.10 验收:5](../learning/07.10-public-problems.md) · [07.10 补记:32](../learning/07.10-public-problems.md) | 真实 MySQL 并发、持久化回滚、排序规则与 Nginx 未验。下线后既有提交可见性待提交接口落地后验证。 |
| 测试数据管理（07.9） | 默认集 710 passed，Ruff 与格式通过，事务替身覆盖在途拒绝及故障回滚。 [07.9 learning:24](../learning/07.9-test-cases.md) | ① 四接口及状态契约离线通过。② 父锁与回滚编排由替身验证。③ 应用层大小保护和仓库三检查通过。在途编辑保护的当前证据覆盖编辑侧，提交侧属 M2。 [07.9 验收:6](../learning/07.9-test-cases.md) · [在途与边界:28](../learning/07.9-test-cases.md) | 真实锁范围、并发、持久化回滚及历史外键 SET NULL 未验。M2 提交接收与限制快照的并发链路待实现。 |

## 证据口径

- 以上历史检查结果来自对应 learning 的当次记录，本轮执行文档 diff 与链接检查。认证真实依赖的已验证部分、07.6–07.10 的离线证据和剩余实库缺口分别保留。
- 2026-11-07 的 07.10 用户 filled 为 41/41，pytest、worker 和命令退出 0，dependency_drift=false、network_attempts=0。该成绩计入个人练习，E1–E3 仍待掌握。 [练习补记](../learning/07.10-public-problems.md#2026-11-07-用户练习补记)
- 本表按 11 月 8 日目标日命名，当前取证日为 11 月 7 日。学习检查、真实 MySQL 与 Nginx 部署层仍有待办，正式 M1 验收待用户审阅。 [README:25](../../README.md)

M1 四项交付离线完成；MVP 附录 A 仍未勾选，实库与提交侧待 M2 及后续验证。

待办包括隔离实库验证和 M2 提交链路。

1. 在隔离测试库补验初始管理员命令、最后管理员并发保护、题库/测试点及发布状态的真实持久化与回滚、排序规则、外键效果和公开样例读取，核对开发库与资源清理。
2. 落地 M2 提交接收、限制快照、幂等与结果白名单，验证其与编辑共用父锁，下线后既有提交可见，并补 Worker/提交并发的隔离与清理证据。
3. 完成 Nginx 部署层请求体限额验证，按学习流程补五项理解检查和关 AI 后独立复现。

## 隔离实库验证准备（2026-11-07）

受控入口已增加 m1-access 与 m1-problems 两个范围，分别收集 7 项、14 项。默认认证范围显式选择原 8 项，M1 应用账号按表授权。默认回归 777 passed，Ruff 与格式通过。上述集成用例目前仅离线收集成功，表中实库状态继续等待批准运行后的报告、清理结果及开发库对照。 [M1 集成记录](../learning/m1-isolated-integration.md)

m1-access 于 2026-11-07 获准首次运行，run_id=5e0dd5006f1f44b88235530ba79c7b85，PREFLIGHT 退出 65。MySQL 容器实际端口与网络挂接为空，数据库连接和资源创建均未进入，七项测试未执行。实库待验状态继续保留。 [失败记录](../learning/m1-isolated-integration.md#m1-access-首次获准实跑2026-11-07)

## M1 隔离实库补验（2026-11-07）

m1-access 已在 run_id=0a761c8e3aa74bd095e0d3aa0faff530 取得 7/7，并经复核确认。收敛提交表权限、补齐报告字段后，m1-problems 在 run_id=07a40887c9bf447ca106616da1cd6b50 取得 14/14，入口退出 0。开发库前后均为 0 表、无 alembic_version 表，development_unchanged=true，容器 ID 前后一致；隔离库、两账号、Redis 前缀残留均为 0，cleanup_errors=[]。此补记更新上文运行前的实库待验快照，个人理解、M2 提交链路和 Nginx 仍待验，附录 A 勾选待用户复核。 [运行与时间记录](../learning/m1-isolated-integration.md#收敛授权后的-m1-problems-实测2026-11-07)
