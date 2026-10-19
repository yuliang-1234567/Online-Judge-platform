# 在线判题系统（OJ）

项目设计文档  v1.2

Project 01 · Python 后端 / Agent 求职主项目

| 文档版本 | v1.2（2026-10-19），替代 v1.1；历史变更保留在附录 C |
| --- | --- |
| 设计定位 | MVP + 可面试深化版 |
| 核心技术 | FastAPI（async）/ MySQL 8 / Redis / Celery / Docker / Vue3 + TypeScript / Nginx |
| 目标阶段 | 2026.10 – 2027.01：核心版本于 2027-01-10 冻结（已确认，见 2.4） |
| 设计依据 | 《求职规划02》中的项目一 OJ 方案；《OJ 设计文档改进点分析》（本版的修改依据） |
| 本版重点 | 权限即时生效 · 隐藏输出保护 · 在途编辑约束与限制快照 · 追踪与幂等分离 · WSL2 与重排里程碑 |

设计原则：　少而深。核心版本优先保证判题链路稳定、可解释、可测试、可部署；比赛、讨论、多语言等均属于后置增强项。v1.1 追加一条：可靠性先于功能——任何会让提交卡死、重复计分、泄露测试数据的缺陷，优先级高于任何新功能。

如何阅读本文：　章节顶部带蓝色竖线的“v1.1 变更”条，说明该章相对 v1.0 改了什么，并给出对应的改进项编号（I-xx / D-xx）；每一项的问题与理由见《OJ 设计文档改进点分析》。附录 C 汇总了全部变更。

v1.2 维护约定：docs/project-design.md 是仓库内持续维护的设计主本；DOCX 原件保留在私有 local-reference/，不入库。历史 v1.1 变更说明保留原版本标记。协作规则见 [ai-workflow.md](ai-workflow.md)，开发准备模板见 [development-workflow.md](development-workflow.md)。OpenAPI、代码与本设计不一致时，先停止并报告，由用户确认处理方案。

## 目录

| 章 | 标题 | 内容 |
| --- | --- | --- |
| 1 | 项目概述 | 定位、来源约束、术语 |
| 2 | 目标与范围 | MVP 范围、非目标、关键默认决策 |
| 3 | 需求定义 | 功能需求、非功能需求、容量假设 |
| 4 | 总体架构 | 分层、取舍、Worker 与 Docker、同步/异步边界 |
| 5 | 核心业务流程 | 提交流程（时序图）、结果查询、状态与终态 |
| 6 | 模块设计 | 九个模块的职责与边界 |
| 7 | 判题沙箱设计 | 信任边界、容器参数基线、判题规则、回收、残余风险 |
| 8 | 状态机、幂等与重试 | 幂等四层、重试、崩溃恢复、Celery 配置、并发推演 |
| 9 | 数据库设计 | ER 图、DDL、索引、EXPLAIN 验证、分析视图 |
| 10 | Redis 设计 | 职责边界、缓存、限流、排行榜、淘汰与隔离 |
| 11 | API 设计 | 约定、30 个接口、结果脱敏 |
| 12 | 安全设计 | 风险表、认证、测试数据保护、资源限制 |
| 13 | 前端设计 | 页面、结果轮询、前端安全 |
| 14 | 部署与运维 | Compose、迁移、可观测性、备份、上线清单与内存预算 |
| 15 | 测试与压测 | 测试层级、判题样例集与故障演练、压测方案、CI |
| 16 | 项目目录结构 | 含 docs/、CI、压测与造数脚本 |
| 17 | 开发里程碑与验收标准 | 带日期的 M1–M4、近期周计划、冻结 |
| 18 | 面试证据链 | 证据索引、高频追问清单、复盘五问 |
| 19 | 非目标与停止线 | 后置优化清单、技术准入三问 |
| 20 | 附录：关键决策记录 | ADR-001 ～ ADR-012 |
| A | 附录 A：MVP 开发验收清单 |  |
| B | 附录 B：需求追踪矩阵 | 需求 → 接口 → 表 → 测试 |
| C | 附录 C：版本变更摘要 |  |

## 1. 项目概述

在线判题系统（Online Judge，OJ）是本求职规划中的第一项目，定位为“Python 后端主项目”。项目不追求做成完整的商业 OJ，而是通过一个完整、可运行、可压测、可部署的后端系统，集中展示异步任务、队列、容器执行、缓存、排行榜、限流、状态机、数据库优化和工程化测试能力。

来源约束：　原规划明确要求保留 OJ，并将核心 MVP 收敛到“用户与 RBAC、题库、提交 → Redis/Celery → 判题 Worker → Docker、结果回写、提交记录、Redis ZSET 排行榜、限流、超时、失败重试、幂等、Vue3/Monaco、Swagger/OpenAPI、Docker Compose、Nginx、云部署”。

本设计文档把这些目标落成可开发的系统结构、接口边界、数据模型、状态机和验收标准。OJ 的具体范围以本设计的 P0/P1 为准；开发准备方案中的“必做/应做/可选”是通用模板，不改变本项目优先级。凡未在原规划中明确的具体参数，以“设计建议”或“初始建议”标识，含义是：先用这个值做出 MVP，上线前用真实测试校准；它们不是原规划的既定事实，更不应直接写进简历。

### 1.1 术语

| 术语 | 含义 |
| --- | --- |
| Verdict | 一次提交的最终判题结论，即状态机中的终态（ACCEPTED、WRONG_ANSWER 等）。 |
| claim（领取） | Worker 用一条带前置条件的 UPDATE，把提交从 QUEUED 改为 RUNNING；受影响行数为 1 的 Worker 才拥有这次判题。 |
| lease（租约） | Worker 持有判题权的有效期，存放在 submissions.lease_expires_at；Worker 判题期间不断续租，崩溃后租约过期，扫描器据此接管。 |
| 围栏（fencing） | 回写结果时用 attempts 作为条件，保证“已被接管的旧 Worker”无法覆盖新结果。 |
| 首次 AC | 某用户第一次通过某道题。排行榜只对“首次 AC”计分，由 user_problem_stats 上的条件更新判定。 |
| 在途提交 | 状态为 QUEUED 或 RUNNING 的提交。每个用户的在途数量有上限，用于防止队列被单个用户灌满。 |
| 补偿扫描 | Celery Beat 定时执行的维护任务：把卡在 QUEUED 的提交重新入队、接管租约过期的 RUNNING 提交、回收孤儿容器。 |
| 事实数据 | 必须持久、可作为唯一依据的数据，存放在 MySQL。Redis 中的队列、缓存、排行榜都可由事实数据恢复。 |

## 2. 目标与范围

v1.1 变更｜新增 FR-11/FR-12 对应的目标；MVP 增加“注册、恢复与补偿、测试数据保护”；非目标补充；新增 2.4 关键默认决策（I-09、I-10、D-04）。

### 2.1 产品目标

- 提供题库浏览、题目详情、代码提交、判题结果查询和提交历史能力。

- 将代码执行与 Web 请求解耦，形成“API → 队列 → Worker → Docker → 结果回写”的异步判题闭环，并且任一环节失败后提交都能自动收敛到终态。

- 通过 Redis 支持排行榜、缓存和限流，体现高频读写场景下的后端设计。

- 通过 MySQL 事务、索引与 EXPLAIN 完成可验证的数据库优化。

- 通过 Pytest、CI、日志、基础压测、Docker Compose 和 Nginx 形成可部署、可维护的工程闭环。

- 保护隐藏测试数据：任何接口、缓存、日志都不得泄露隐藏用例的输入与期望输出。

### 2.2 MVP 范围

| 域 | MVP 内容 | 优先级 |
| --- | --- | --- |
| 账号与权限 | 注册/登录、JWT、RBAC、基础用户信息；角色与账号状态以数据库为准 | P0 |
| 题库 | 题目创建/编辑/发布/下线、标签、分页查询、题目详情、测试数据管理（区分样例与隐藏用例） | P0 |
| 提交 | 提交代码（Idempotency-Key 必填）、语言、题目、提交记录（游标分页）、状态查询 | P0 |
| 判题 | Redis/Celery 入队、Worker、Docker 沙箱、Worker 侧比对、结果回写 | P0 |
| 可靠性 | 状态机条件更新、lease 与崩溃恢复、入队补偿、有限重试、孤儿容器回收 | P0 |
| 缓存与排行榜 | 题目缓存（穿透/击穿/雪崩处理）、Redis ZSET 排行榜（首次 AC 计分，可重建） | P0 |
| 稳定性 | 限流（含在途提交上限）、超时、失败重试、幂等 | P0 |
| 前端 | Vue3 + TS + Element Plus + Monaco Editor | P0 |
| 工程化 | Swagger/OpenAPI、Pytest、GitHub Actions、Docker Compose、Nginx、日志与健康检查、云部署 | P0 |
| 判题语言 | Python 3 先打通全链路；C++ 作为第二语言放 M3，进度落后则砍 | P0 / P1 |
| 增强 | 比赛、题解、评论、更多语言、性能排行、重判、SSE 推送等（见 19.2） | P1 |

### 2.3 非目标

- 不以商业级大规模分布式 OJ 为目标；不做多机 Worker 调度。

- 不同时建设 Celery Worker 与另一套自建任务调度框架。

- 不在 MVP 阶段支持过多编程语言；先稳定 1–2 种。

- 不把沙箱做成独立安全产品；重点是公开部署环境下的基本隔离、资源限制与异常回收，并如实说明残余风险（7.6）。

- 不做特殊判题（Special Judge）、浮点容差、交互题、部分得分；比对规则见 7.3。

- 不做重判（rejudge）、第三方登录、邮箱验证、refresh token；它们的触发条件见 19.2。

### 2.4 关键默认决策

下面8项由v1.1提出，在v1.2按用户决定确认；冻结日与ID范围采用本次批准值。具体可靠性机制按17.3留到W5复核，不能据此提前改变流程。

| # | 决策点 | v1.2 确认的选择 |
| --- | --- | --- |
| 1 | 题库与排行榜是否匿名可读 | 匿名可读（按 IP 限流）；提交与个人数据需登录；README 提供演示账号。 |
| 2 | Worker 访问 Docker 的方式 | Worker 容器挂载 docker.sock；用户代码容器没有任何 socket 挂载（ADR-008）。 |
| 3 | 排行规则 | 按通过题数降序；同分时，“最后一次首次通过的时间”早者在前。 |
| 4 | 判题容器粒度 | 每个测试点一个一次性容器（ADR-011）。 |
| 5 | 首批语言 | M2 先用 Python 打通；C++ 放 M3，延期则砍。 |
| 6 | 冻结日期 | 2027-01-10（已确认）；压测与故障演练在 2026 年 12 月完成；进度不足只削减范围，不跳过严格级理解与正确性检查。 |
| 7 | 登出与 refresh token | MVP 只做短期 access token，不做 refresh 与吊销黑名单。 |
| 8 | ID 形式 | BIGINT 自增；项目规模下 ID 远小于 2^53，接口继续返回数字；访问控制靠“归属校验”，不靠 ID 不可猜。 |

## 3. 需求定义

v1.1 变更｜新增 FR-11（测试数据保护）、FR-12（运维可见）；FR-09 增加崩溃恢复；非功能需求增加“可恢复性”“数据保护”；新增 3.3 容量假设（I-02、I-08、I-18）。

### 3.1 功能需求

| ID | 需求 | 说明 | 级别 |
| --- | --- | --- | --- |
| FR-01 | 认证与授权 | 用户可注册、登录并获得 JWT；后端基于 RBAC 控制普通用户与管理员接口；角色与账号状态以数据库为准，禁用账号立即生效。 | P0 |
| FR-02 | 题库管理 | 管理员能够创建、编辑、发布、下线题目，维护标签与测试数据（区分样例与隐藏用例）；普通用户可分页浏览已发布题目。 | P0 |
| FR-03 | 代码提交 | 用户选择题目与语言提交代码，必须携带 Idempotency-Key；系统生成唯一 submission_id 并立即返回 202 与“排队中”状态。 | P0 |
| FR-04 | 异步判题 | 提交任务进入 Redis/Celery；Worker 取出后为每个测试点创建一次性 Docker 沙箱执行，并在 Worker 侧比对输出。 | P0 |
| FR-05 | 结果持久化 | 保存状态、通过用例数/总用例数、错误码与摘要、运行时间、内存、各阶段时间点（入队/开始/完成）。 | P0 |
| FR-06 | 提交历史 | 用户可按题目/状态分页查询个人提交记录（游标分页）。 | P0 |
| FR-07 | 排行榜 | 按“通过题数”降序，同分先完成者在前；只对首次 AC 计分；Redis ZSET 提供快速排序，可由 MySQL 重建。 | P0 |
| FR-08 | 限流与超时 | 对登录、注册、提交和高频查询设置限流；每用户在途提交数有上限；单次判题必须有执行时间上限。 | P0 |
| FR-09 | 重试、幂等与恢复 | 系统性失败可有限次重试；重复投递不得造成重复判题或重复计分；Worker 崩溃后提交能自动恢复或进入 FAILED。 | P0 |
| FR-10 | 管理端 | 管理员能够管理题目、测试数据、标签、用户，查看提交记录、审计日志与队列状态。 | P0 |
| FR-11 | 测试数据保护 | 隐藏用例的输入与期望输出不得经题目接口、缓存、提交结果、日志外泄；样例用例可以展示。 | P0 |
| FR-12 | 运维可见 | 提供健康检查；能按 submission_id 追踪任务、容器与结果；管理员可查看队列长度与在途数量。 | P0 |

### 3.2 非功能需求

| 维度 | 要求 | 验收方式 |
| --- | --- | --- |
| 正确性 | 同一题目、同一测试数据下，判题结果可重复；态最终收敛到终态。状 | 集成测试 + 判题样例集（15.2） |
| 可恢复性 | Worker 崩溃、Redis 重启、入队失败后，提交在“lease 时长 + 扫描周期 + 判题时长”内重新得到结果或进入 FAILED（初始建议：lease 60 s、扫描 30 s）。 | 故障演练（15.2） |
| 安全性 | 代码执行与宿主机隔离；限制 CPU/内存/时间/进程/输出；不向代码提供宿主机敏感权限；期望输出不进入容器。 | 沙箱样例集 + 安全检查清单 |
| 数据保护 | 隐藏测试数据不外泄；密码以强哈希存储；日志不含密码、Token、完整代码。 | 接口测试 + 日志检查 |
| 可用性 | API 与判题 Worker 解耦，Worker 短时不可用不拖垮 Web API；API 不可用时已入队任务仍可完成。 | 停止/恢复 Worker 测试 |
| 可维护性 | 核心 Service 有单元测试；统一日志与异常处理；CI 自动运行测试与构建。 | Pytest + GitHub Actions |
| 可观测性 | 能够定位 submission_id 对应的请求、任务、容器和最终结果；能区分排队时间与判题耗时。 | 日志链路检查（14.4） |
| 性能 | 通过 Locust 或同类工具获得真实 QPS/延迟数据，区分入队延迟与端到端时延；不虚构简历数字。 | 压测报告（15.3） |

### 3.3 容量假设

本项目面向演示与面试，不追求高并发。下面的假设用来约束设计规模，也用来解释“为什么单机 Compose 就够”；它们是设计假设，不是性能承诺。

| 项 | 假设 | 用途 |
| --- | --- | --- |
| 目标机型 | 2 vCPU / 4 GB 内存的云服务器（学生机常见配置，以实际购买为准） | 决定 Worker 并发与内存预算（14.6） |
| 判题并发 | Worker 并发度 2（同时最多 2 个判题容器） | 决定吞吐上限与队列堆积行为 |
| 数据规模 | 用户 ≤ 10³，题目 ≤ 10²；压测前造数至 10⁶ 级提交记录 | 让 EXPLAIN 优化前后有可观察的差异 |
| 单次提交 | 代码 ≤ 32 KB；单题测试点 ≤ 50 个；单点输入/输出 ≤ 1 MB（初始建议） | 决定 9.5 的大字段上限与超时计算 |
| 峰值提交 | 按“每秒几次到几十次入队”压测，目的是观察队列削峰，而非追求绝对 QPS | 决定压测场景（15.3） |

## 4. 总体架构

v1.1 变更｜重绘架构图；新增 4.3（Worker 与 Docker 的关系）、4.4（同步/异步边界）、4.5（版本基线）；取舍表补充（I-04、I-05、I-13、I-17、D-01）。

### 4.1 分层结构

- 接入层：Vue3 + TypeScript + Monaco Editor；Nginx 负责反向代理、HTTPS 与请求体大小限制。

- API 层：FastAPI（async），负责认证、题库、提交、查询、管理等同步请求；不执行用户代码。

- 数据层：MySQL 负责业务事实数据；Redis 负责队列 broker、缓存、排行榜、限流与锁（单实例，noeviction）。

- 任务层：Celery Worker 从 judge 队列取任务并调度 Docker；Celery Beat 定时执行补偿扫描、孤儿回收与榜单重建。

- 执行层：Docker 容器完成编译、运行与资源约束；比对在 Worker 侧完成，期望输出永不进入容器。

[图1 Mermaid 单一来源](figures/architecture.md)（[v1.1 原图存档](figures/reference/architecture-v1.1.png)）

图 1  OJ 总体架构（v1.2 修正任务来源、Beat 调度方向及 Docker 访问方向）

### 4.2 核心设计取舍

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 异步任务 | Celery + Redis | 原规划要求异步化；可表达削峰、重试、任务状态和幂等。可靠性以“MySQL 状态机 + lease 扫描”为准，不依赖 broker 的重投语义（ADR-002、ADR-009）。 |
| 任务执行 | Celery Worker 调 Docker | 避免将 Docker 编排和 API 服务耦合在一起；只有 Worker 接触 Docker daemon（ADR-008）。 |
| 容器粒度 | 每个测试点一个一次性容器 | 隔离最干净、实现最直观；启动开销用实测评估，必要时再优化（ADR-011）。 |
| 排行榜 | Redis ZSET + user_problem_stats | ZSET 支持排序与名次查询；“首次 AC”由 MySQL 条件更新判定；榜单可整体重建（ADR-004、ADR-010）。 |
| 业务数据库 | MySQL | 满足用户、题目、提交、判题结果等关系型数据的一致性要求。 |
| Redis 部署 | 单实例，noeviction，db0 broker / db1 其余 | 队列键绝不能被淘汰；缓存键必带 TTL；实测互相影响再拆实例（ADR-012）。 |
| API 并发模型 | async 路由，Worker 同步 | I/O 密集的 API 用 async；Worker 为 prefork 同步进程，天然适配 Docker SDK（ADR-007）。 |
| 前端编辑器 | Monaco Editor | 接近真实代码编辑器体验，适合展示项目完成度。 |
| 部署 | Docker Compose + Nginx | 减少部署复杂度，同时能展示容器化与反向代理能力。 |

### 4.3 Worker 与 Docker 的关系

Worker 要启动判题容器，自己就必须能访问 Docker daemon。这与“用户代码容器不得接触宿主机 Docker Socket”并不矛盾——两者是不同的信任等级：

| 角色 | 信任等级 | 能访问什么 | 不能访问什么 |
| --- | --- | --- | --- |
| API 容器 | 可信 | MySQL、Redis（经内部网络） | Docker daemon、judge 工作目录 |
| Worker 容器 | 可信（高权限） | Docker daemon、judge 工作目录、MySQL、Redis | 公网入站流量（不对外暴露端口） |
| 判题容器 | 不可信 | 只读的代码与当前用例输入、可写的输出目录 | 网络、宿主机文件、docker.sock、期望输出、其他提交的目录 |

已知风险：　挂载 docker.sock 等价于给 Worker 进程宿主机 root 级权限。MVP 接受这一点，并用三条措施缓解：Worker 与公网服务分属不同容器、不对外暴露任何端口；Worker 代码只调用有限的 Docker API；记录在 ADR-008，并把 docker-socket-proxy 与 rootless Docker 列为可选加固（7.6）。

- 临时目录路径要一致：Worker 在容器内创建的工作目录，要挂载给判题容器时，bind mount 的源路径由宿主机的 Docker 解析。因此使用“宿主机路径与容器内路径相同”的 bind mount（例如两边都是 /var/oj/judge-work），避免挂载到不存在的路径。

开发环境：工程位于 WSL2 Ubuntu 的 Linux 文件系统，例如 ~/projects/oj-platform，不在 /mnt/d 下开发；Windows D 盘仅保留文档备份。先评估 WSL 内原生 Docker Engine，Docker Desktop 作为备选，具体结果见 ADR-016。环境验收必须实际完成“Worker 写文件 → 判题容器读到同一文件 → 非 root 写输出 → 清理成功”，不以路径字符串相同代替验证。阶段06末尾探针限时半天，失败不阻塞认证切片，结果及原因写入 ADR-016 与 learning。

- 判题镜像预先构建：运行时不拉镜像、不联网；镜像随部署脚本构建并在启动前校验存在。

### 4.4 同步与异步的边界

| 组件 | 模型 | 说明 |
| --- | --- | --- |
| FastAPI 路由 | async | SQLAlchemy 2.0 async（asyncmy 或 aiomysql 驱动）+ redis.asyncio；使用 pool_pre_ping。 |
| CPU 密集操作 | 线程池 | 密码哈希（argon2/bcrypt）放入 run_in_threadpool，避免阻塞事件循环。 |
| Celery Worker | 同步（prefork） | SQLAlchemy 同步引擎（pymysql）+ Docker SDK；每个子进程在 worker_process_init 中创建自己的引擎。 |
| Celery Beat | 单实例 | 只运行一个；扫描逻辑全部幂等，误起两个也不会出错（8.3）。 |
| 禁止事项 | — | 禁止在 async 路由里调用阻塞库（同步 ORM、requests、time.sleep）；若必须调用，放入线程池。 |

### 4.5 版本基线

只列大版本，具体版本以 pyproject.toml 与 package.json 的锁定文件为准。

| 组件 | 大版本 | 说明 |
| --- | --- | --- |
| Python | 3.12 | 后端与 Worker 统一版本；判题镜像里的 Python 版本单独声明。 |
| MySQL | 8.0 | utf8mb4；InnoDB；DATETIME(3)。 |
| Redis | 7.x | 使用 ZADD … GT（Redis ≥ 6.2）与 Lua 脚本。 |
| Celery | 5.x | broker 使用 Redis。 |
| SQLAlchemy / Alembic | 2.0 / 1.x | async 与 sync 两种会话共用同一套模型。 |
| Vue / TypeScript | 3 / 5 | Element Plus、Pinia、Axios、Vue Router。 |

## 5. 核心业务流程

v1.1 变更｜提交流程改为“落库事务 → 提交后入队 → claim → finalize”，并配时序图；新增 5.2 查询策略；状态机新增 OUTPUT_LIMIT 与恢复路径，明确判题规则与错误码（I-02、I-03、I-07、D-01）。

### 5.1 提交流程

下面的编号与图 2（见本节末尾）一一对应：

1. 浏览器调用 POST /api/v1/submissions，携带 Authorization、Idempotency-Key，请求体包含题目、语言与代码。Nginx 先做请求体大小限制。

2. FastAPI 依次完成：鉴权 → 限流 → 参数校验（题目已发布、语言受支持、代码长度合法）→ 在途提交上限检查。

3. 同一个事务内：写入 submissions（QUEUED，queued_at 为当前时间）；若 (user_id, idempotency_key) 冲突，说明是重放：不再增加任何计数，直接读取并返回已有记录；否则对 user_problem_stats 做 upsert 并 attempts + 1，同时保存本次使用的时间、内存限制快照；COMMIT。提交接收与题目编辑的事务协调方式在 M1 严格级设计中确认。

4. COMMIT 之后才向 judge 队列投递 submission_id。入队失败只记录日志，不影响响应——记录已持久化，由补偿扫描兜底（8.3）。

5. 返回 202 Accepted：{submission_id, status: QUEUED}。

6. Worker 从 judge 队列取任务（延迟确认，见 8.4）。

7. claim：条件更新 QUEUED → RUNNING，同时写入 attempts + 1、worker_id、lease_expires_at；受影响行数为 0 说明已被他人处理或已是终态，任务直接结束。

8. 读取题目与测试数据，运行限制使用该提交保存的快照；需要编译则先在受限容器内编译；然后每个测试点启动一个新容器，运行、等待、取输出（期望输出不进入容器）。

9. Worker 侧按 7.3 的规则比对；遇到第一个非 AC 的测试点即停止；每个测试点结束后续租。

10. finalize（一个事务）：条件更新 RUNNING → 终态（以 attempts 作围栏）→ 写 submission_cases → 若为 AC，条件更新 user_problem_stats.solved；COMMIT。

11. 若本次是该用户对该题的首次 AC：事务提交后重新计算 score，ZADD … GT 更新排行榜；失败则登记一次榜单刷新任务（10.4）。

12. finally：无论成功、失败、超时，都删除容器与临时目录。

13. 浏览器轮询 GET /api/v1/submissions/{id}（退避策略见 5.2）。

14. 服务端返回当前状态；终态时附带结果，隐藏用例已脱敏（11.5）。

关键原则：　HTTP 请求只负责“接收提交并排队”，不要在 FastAPI 请求线程内编译或运行用户代码；先提交事务，再入队；每一次状态变更都带前置条件。

[图2 Mermaid 单一来源](figures/submission-sequence.md)（[v1.1 原图存档](figures/reference/submission-sequence-v1.1.png)）

图 2  提交与判题时序（含失败路径）

### 5.2 结果查询策略

- MVP 使用轮询：前端从 1 s 开始，逐步退避到 5 s；状态进入终态即停止；页面不可见时暂停。

- 查询接口只读 MySQL 的主键行，成本很低；是否需要 Redis Hash 或 SSE，由压测中“轮询带来的读压力”决定（19.2），不预先实现。

- QUEUED 超过 30 s 时，前端提示“排队较久，系统仍在处理”，避免用户重复提交。

### 5.3 状态与终态

[图3 Mermaid 单一来源](figures/submission-state.md)（[v1.1 原图存档](figures/reference/submission-state-v1.1.png)）

图 3  提交状态机

| 状态 | 含义 | 允许的下一状态 |
| --- | --- | --- |
| QUEUED | 已落库并入队（也包括被重置后重新入队） | RUNNING；FAILED（入队多次失败仍无人领取） |
| RUNNING | 某个 Worker 已 claim，且 lease 未过期 | 任一判题终态；QUEUED（可重试错误，或 lease 过期且 attempts 未达上限）；FAILED（重试用尽或不可重试的系统错误） |
| ACCEPTED | 全部测试点通过 | 终态 |
| WRONG_ANSWER | 某个测试点输出不一致 | 终态 |
| COMPILE_ERROR | 编译失败（含编译超时、编译输出超限） | 终态 |
| RUNTIME_ERROR | 非零退出码或被信号终止 | 终态 |
| TIME_LIMIT | 超出时间限制 | 终态 |
| MEMORY_LIMIT | 超出内存限制 | 终态 |
| OUTPUT_LIMIT | 输出超出上限（v1.1 新增） | 终态 |
| FAILED | 系统异常：重试用尽、Worker 丢失、入队耗尽等，error_code 说明原因 | 终态 |

FAILED 的 error_code：INFRA_ERROR（容器启动失败、Docker 不可用等，重试用尽）、WORKER_LOST（lease 多次过期）、ENQUEUE_EXHAUSTED（反复补偿入队仍无人领取）、INTERNAL_ERROR（未预期异常）。

状态机性质：　(1) 终态不可再变；(2) 所有状态变更都是“带前置条件的 UPDATE”，受影响行数为 0 就当作“别人已处理”；(3) 只有 RUNNING → QUEUED 一条回退边，且只能由“持有最新 attempts 的 Worker”或“扫描器”执行。

## 6. 模块设计

v1.1 变更｜模块改为独立小节（便于引用）；新增“判题执行器”“维护任务”两个模块，判题调度模块增加 claim/finalize/lease 职责；题库模块明确 DTO 分离（I-02、I-08、D-02）。

### 6.1 用户与认证（auth）

| 职责 | 注册、登录、密码校验、JWT 签发与校验、角色与权限。 |
| --- | --- |
| 设计要点 | 密码用 argon2id（或 bcrypt）哈希；JWT 固定算法、短有效期；每次鉴权按 sub 对应的用户主键查询角色与账号状态，MVP 不缓存二者，禁用账号、降权立即生效。只有压测证明必要，才通过新的 ADR 讨论缓存。 |
| 边界 | 普通用户只能访问自己的提交；管理员接口统一在 /api/v1/admin 下，由同一个依赖项做角色校验。 |

初始管理员由 scripts/create_admin.py 一次性命令创建；密码来自环境变量或交互输入，不写入迁移、源码、命令行参数或日志。具体认证与事务实现由用户在 M1 严格级设计后编写；阶段06不实现该命令。

### 6.2 题库（problem）

| 职责 | 题目、标签、难度、时间/内存限制、测试数据、发布/下线。 |
| --- | --- |
| 设计要点 | 对外 DTO 与管理端 DTO 严格分离：对外只含题面与样例用例；完整测试数据只在管理员接口出现。题目详情可缓存，缓存的是对外 DTO（10.2）。 |
| 边界 | 题目发布前必须至少有 1 个测试点且至少 1 个样例。有 QUEUED/RUNNING 提交时，禁止增删改测试点（包括顺序和样例标记）及修改时间、内存限制。提交接收与管理员编辑必须在并发下共同满足此约束，不能只“先查数量再修改”；具体事务方案在 M1 严格级设计中由用户确认。提交记录使用的限制快照；不重判历史提交。 |

### 6.3 提交（submission）

| 职责 | 接收代码、生成 submission_id、写入初始状态、查询详情与历史。 |
| --- | --- |
| 设计要点 | 提交记录是判题链路的核心事实数据，不依赖 Redis 作为最终事实来源；创建提交是一个数据库事务（提交记录 + 尝试次数），事务提交后才入队。 |
| 边界 | 只负责“记录与入队”，不碰 Docker；状态的后续变更全部交给判题调度模块。 |

### 6.4 判题调度（judge_service）

| 职责 | 入队、claim、续租、finalize、重试与状态重置。 |
| --- | --- |
| 设计要点 | 把 8.1–8.3 的规则封装成少量带条件的函数：claim()、renew_lease()、finalize()、reset_for_retry()、mark_failed()。每个函数返回“是否成功”，调用方据此决定是否继续。 |
| 边界 | 不关心容器怎么跑；通过接口调用判题执行器，因此可以用假的执行器写单元测试。 |

### 6.5 判题执行器（judge/）

| 职责 | 准备工作目录、编译、为每个测试点启动容器、收集输出、比对、映射 Verdict。 |
| --- | --- |
| 设计要点 | 拆成 DockerRunner（唯一接触 Docker SDK 的类）、Compiler、Comparator（纯函数）、languages（语言配置表）。比对在 Worker 进程内完成。 |
| 边界 | 执行器不读写业务表；输入是“代码 + 测试点列表 + 限制”，输出是“每个测试点的结果”。 |

### 6.6 判题 Worker（tasks/）

| 职责 | Celery 任务的薄封装：取任务 → claim → 调用执行器 → finalize → 清理。 |
| --- | --- |
| 设计要点 | 任务函数里不写业务规则；finally 保证清理；异常按“可重试 / 不可重试”分类处理（8.2）。 |
| 边界 | Worker 必须能够安全回收容器与临时文件；它是可信组件，但不对外暴露任何端口。 |

### 6.7 排行榜（ranking）

| 职责 | 维护 oj:ranking:total，提供 Top N 与个人名次查询，支持整体重建。 |
| --- | --- |
| 设计要点 | 计分以 user_problem_stats 的“首次 AC”为准；score 编码同时包含通过题数与完成时间（10.4）；写入用 ZADD … GT，幂等且抗乱序。 |
| 边界 | 高频读取走 Redis；MySQL 保留可重建依据；榜单与 MySQL 漂移时以 MySQL 为准。 |

### 6.8 维护任务（maintenance，v1.1 新增）

| 职责 | 补偿入队、租约过期接管、孤儿容器与临时目录回收、榜单重建与刷新。 |
| --- | --- |
| 设计要点 | 全部由 Celery Beat 触发、走独立的 maintenance 队列，避免被判题任务阻塞；所有动作都是幂等的条件更新（8.3）。 |
| 边界 | 只修复“状态不一致”，不做业务决策；每次扫描有数量上限，防止一次处理过多。 |

### 6.9 管理端与审计（admin）

| 职责 | 题目、测试数据、标签、用户、提交记录、队列状态、审计日志。 |
| --- | --- |
| 设计要点 | 所有写操作都经过角色校验并写入 audit_logs（谁、做了什么、对哪个资源、请求 ID）；审计只记录摘要，不记录完整测试数据。 |
| 边界 | 管理端与普通端共用同一前端工程，通过路由与接口前缀区分。 |

### 6.10 日志与可观测性（observability）

| 职责 | 结构化日志、request_id 贯穿、健康检查、队列与耗时指标。 |
| --- | --- |
| 设计要点 | X-Request-ID 中间件 + contextvars；日志固定字段 request_id / submission_id / task_id / attempt；耗时由三个时间点推导（14.4）。 |
| 边界 | 不引入 Prometheus/Grafana；指标通过日志与管理端接口呈现，足够支撑压测与演示。 |

## 7. 判题沙箱设计

v1.1 变更｜整章重写：明确信任边界与容器粒度；给出 Docker 参数基线、判题规则、Verdict 优先级、回收机制与残余风险；期望输出不进入容器（I-05、I-06、I-07、I-08、I-25）。

### 7.1 安全目标与信任边界

原规划明确提醒：判题沙箱属于高风险、高复杂度模块，项目不应把自己逼成安全产品公司，但至少要做到公开环境下的基本资源隔离、超时控制、异常回收和权限收缩。

- 用户代码容器不得接触宿主机 Docker Socket，不挂载任何宿主机敏感目录；只挂载“只读的代码与当前用例输入”和“可写的输出目录”。

- 限制 CPU、内存、执行时长、进程数、输出大小和文件大小；默认关闭网络。

- 期望输出永不进入容器；比对在 Worker 侧完成，用户程序无从读取标准答案。

- 每个测试点使用独立的一次性容器和独立的输出目录，用户之间、测试点之间不复用运行目录。

- 执行完成、超时或异常后都必须回收容器和临时文件；Worker 自己崩溃时由孤儿回收兜底（7.5）。

- 编译阶段同样在受限容器内执行，并限制耗时、内存与输出大小。

设计建议（非原规划硬性参数）：　下面的 CPU、内存、时间、进程数和输出大小都是初始建议，用真实题目与压测逐步校准；它们不应直接写进简历作为固定指标。

### 7.2 容器参数基线

| 项 | Docker 选项 | 初始建议 | 作用 |
| --- | --- | --- | --- |
| 网络 | --network none | 运行与编译均关闭 | 防止访问外部服务与内网。 |
| 内存 | --memory = --memory-swap | 题目限制 + 64 MB 余量 | 禁用 swap；余量保证解释器可启动，超限由峰值内存判 MLE，失控程序被 OOM 终止。 |
| CPU | --cpus | 1 | 避免单个提交占满核心。 |
| 进程数 | --pids-limit | 运行 64；编译 128 | 抵御 fork 炸弹；编译器会派生子进程，需更高。 |
| 文件系统 | --read-only + --tmpfs /tmp | tmpfs ≤ 16 MB | 根文件系统只读，只有 /tmp 和输出目录可写。 |
| 权限 | --cap-drop ALL、--security-opt no-new-privileges | 全部丢弃 | 收缩 capability，阻止提权。 |
| 用户 | --user | 镜像内固定的非 root uid | 容器内不使用 root。 |
| 文件与句柄 | --ulimit fsize、nofile、core | fsize = 输出上限；nofile 64；core 0 | 限制输出文件大小、文件句柄与 core dump。 |
| 安全配置 | 默认 seccomp / AppArmor | 保留默认，不使用 unconfined | 默认配置已拦截一批高危系统调用。 |
| 挂载 | /work（只读）、/out（读写） | 仅此两处 | 代码与输入只读；输出目录每个测试点独立。 |
| 标签与命名 | --label oj.judge=1、oj.sid、oj.created | 必带 | 孤儿容器回收按标签识别（7.5）。 |

以上参数用 Docker SDK for Python 的同名参数设置；示意如下，非最终实现。

```python
container = client.containers.run(
    image=lang.image, command=cmd, detach=True,
    network_mode="none",
    mem_limit=f"{limit_mb + 64}m", memswap_limit=f"{limit_mb + 64}m",
    nano_cpus=1_000_000_000, pids_limit=64,
    read_only=True, tmpfs={"/tmp": "size=16m,mode=1777"},
    cap_drop=["ALL"], security_opt=["no-new-privileges"],
    user="10001:10001",
    ulimits=[docker.types.Ulimit(name="fsize", soft=out_limit, hard=out_limit),
             docker.types.Ulimit(name="nofile", soft=64, hard=64),
             docker.types.Ulimit(name="core", soft=0, hard=0)],
    volumes={work_dir: {"bind": "/work", "mode": "ro"},
             out_dir:  {"bind": "/out",  "mode": "rw"}},
    labels={"oj.judge": "1", "oj.sid": str(sid), "oj.created": now_iso},
)
```

### 7.3 判题规则

#### 7.3.1 输出比对

默认比对器以 UTF-8 编码的期望输出和用户程序原始输出字节为输入：先将 CRLF 规整为 LF；每行仅移除末尾 ASCII 空格（0x20）、制表符（0x09）和回车（0x0D）；随后删除输出末尾空行，其他字节保持原样后比较。不做 Unicode 归一化，不忽略 NBSP 等其他 Unicode 空白，也不以替换字符吞掉非法 UTF-8 字节。不做浮点容差或特殊判题。

规则示例（文档约定，尚非已执行的测试）：

| 期望 / 实际差异 | 结论 |
| --- | --- |
| 仅 CRLF、ASCII 行尾空格/制表符/回车、末尾空行不同 | 相同 |
| 行首空格或行内空白不同 | 不同 |
| 行尾多出 NBSP（U+00A0） | 不同 |
| 预组字符与组合字符仅视觉相同 | 不同 |
| 非法 UTF-8 字节与文本 U+FFFD | 不同，不能通过 replace 解码变为相同 |

Comparator 核心实现留到对应小节，由用户按该规则编写；本次移除会扩大空白范围的示意实现。

#### 7.3.2 测试点汇总与 Verdict 优先级

- 测试点按 case_index 依次运行，遇到第一个非 AC 即停止；提交的 Verdict 取该测试点的结果；全部通过才是 ACCEPTED。不做部分得分。

- 单个测试点按下表从上到下判定，命中即停：

| 优先级 | 条件 | Verdict |
| --- | --- | --- |
| 1 | 容器被 OOM 终止（State.OOMKilled），或峰值内存超过题目限制 | MEMORY_LIMIT |
| 2 | 运行超时：入口脚本的超时终止，或 Worker 侧兜底超时 | TIME_LIMIT |
| 3 | 输出文件达到输出上限 | OUTPUT_LIMIT |
| 4 | 退出码非 0，或被信号终止 | RUNTIME_ERROR |
| 5 | 以上都没有，则做输出比对：一致 / 不一致 | （继续）/ WRONG_ANSWER |

- 编译阶段：编译失败、编译超时（初始建议 10 s）、编译输出超过上限（初始建议 64 KB）都判 COMPILE_ERROR；用户只能看到截断后的编译输出（初始建议 2 KB）。

- 输出上限：min(max(10 × 期望输出大小, 64 KB), 16 MB)（初始建议）。

- 兜底超时：Worker 侧等待容器的时间 = 题目时限 + 固定余量（初始建议 2 s），防止入口脚本自身被挂住；到时强制终止容器。

- 时间与内存的口径：入口脚本在容器内以 timeout 包住用户程序，并记录运行耗时与峰值常驻内存；这是近似值，用于判定与展示，不作为精确计量。容器启动与镜像加载时间不计入运行耗时。上述口径与 timeout 的退出码约定，用判题样例集（15.2）实测确认。

### 7.4 判题步骤

- 准备临时工作目录（宿主机与 Worker 容器内路径一致），写入用户代码；为每个测试点准备独立的 in.txt 与输出目录。

- 根据语言选择预构建的运行镜像（Python 与 C++ 各一个，运行时不拉取镜像）。

- 需要编译的语言：在受限容器内编译，产物写入工作目录；编译失败直接得到 COMPILE_ERROR。

- 按 case_index 顺序处理每个测试点：创建容器 → 启动 → 等待（带兜底超时）→ 读取 out.txt（最多读取输出上限 + 1 字节）与退出信息。

- 按 7.3.2 的优先级判定该测试点结果；非 AC 即停止后续测试点。

- 通过 exit_code、OOM 标志与统计文件采集：退出码、运行时间、峰值内存、stdout、stderr（均截断）。

- 每个测试点结束后续租（renew_lease）；若续租失败（行数为 0），说明本 Worker 已被接管，立即中止并清理，不写任何结果。

- 汇总得到最终 Verdict，交给 finalize() 写回（8.1）。

- 无论成功、失败、超时，都在 finally 中删除容器与临时目录。

### 7.5 回收与清理

| 对象 | 正常路径 | 异常兜底 |
| --- | --- | --- |
| 判题容器 | 测试点结束后在 finally 中 remove(force=True) | Beat 每 5 分钟列出带 oj.judge=1 标签且存活超过阈值（初始建议 10 分钟）的容器，强制删除。 |
| 临时工作目录 | finally 中递归删除 | Beat 清理超过阈值（初始建议 30 分钟）且对应提交不在 RUNNING 的目录。 |
| 判题镜像 | 随部署构建，不清理 | 磁盘告警时手动处理；不做自动 docker system prune，避免误删判题镜像。 |
| 日志 | 容器日志不落盘（只取需要的输出） | Docker 日志驱动设置 max-size / max-file（14.6）。 |

### 7.6 残余风险声明与可选加固

残余风险：　普通 Docker 容器与宿主机共享内核，容器逃逸类漏洞可以绕过上述全部限制；挂载 docker.sock 的 Worker 一旦被攻破，等价于宿主机被攻破。本项目的目标是“合理的公开环境防护”，不宣称达到成熟 OJ 平台或专业沙箱产品的安全等级。

| 可选加固 | 效果 | 是否纳入 MVP |
| --- | --- | --- |
| gVisor 等用户态内核运行时 | 缩小用户代码直接面对宿主机内核的攻击面 | 否（配置项预留 --runtime） |
| rootless Docker | 即使逃逸也不是宿主机 root | 否 |
| docker-socket-proxy | 限制 Worker 可调用的 Docker API 范围 | 否（ADR-008 中作为备选） |
| 云上隔离 | 判题机与业务机分离、安全组限制出站 | 否 |
| 保持镜像与内核更新 | 修补已知漏洞 | 是（上线检查清单，14.6） |

## 8. 状态机、幂等与重试

v1.1 变更｜幂等拆成四层；新增 lease、attempts 围栏、补偿扫描与崩溃恢复；新增 Celery 可靠性配置基线与并发场景推演；排行榜防重复计分改为“首次 AC 条件更新”（I-01、I-02、I-03、I-04）。

### 8.1 幂等策略

幂等不是一个开关，而是四个位置各自的保证：

| 层 | 要防止什么 | 机制 |
| --- | --- | --- |
| 提交请求 | 用户重复点击、网络重试造成多条提交 | Idempotency-Key 必填；(user_id, idempotency_key) 唯一索引兜底；冲突时读取并返回原记录，同一个 key 忽略后续请求体差异。 |
| 任务领取 | broker 重复投递、补偿重复入队造成重复判题 | claim 是 WHERE status='QUEUED' 的条件更新；行数为 0 的 Worker 直接结束。 |
| 终态写入 | 旧 Worker 复活后覆盖新结果 | finalize 的条件是 status='RUNNING' AND attempts=:我领取时的值；行数为 0 则丢弃结果。 |
| 排行榜计分 | 同一用户反复 AC 同一题而重复加分 | user_problem_stats 上 WHERE solved=0 的条件更新；受影响行数为 1 才算首次通过；榜单用 ZADD … GT 写入。 |

三条核心 SQL（示意，非最终实现）：

```sql
-- claim：只有一个 Worker 能把 QUEUED 改为 RUNNING
UPDATE submissions
   SET status='RUNNING', attempts=attempts+1, worker_id=:wid,
       started_at=NOW(3), lease_expires_at=NOW(3) + INTERVAL :lease SECOND
 WHERE id=:sid AND status='QUEUED';
-- 受影响行数 = 0 → 已被他人处理或已是终态，任务直接结束
```

```sql
-- renew_lease：每个测试点之后续租；行数 = 0 → 已被接管，立即中止
UPDATE submissions
   SET lease_expires_at = NOW(3) + INTERVAL :lease SECOND
 WHERE id=:sid AND status='RUNNING' AND attempts=:my_attempt;
```

```sql
-- finalize：以 attempts 作围栏回写终态；行数 = 1 才继续写明细与计分
UPDATE submissions
   SET status=:verdict, passed_cases=:p, total_cases=:t,
       runtime_ms=:rt, memory_kb=:mem, error_code=:ec, error_message=:em,
       finished_at=NOW(3), lease_expires_at=NULL
 WHERE id=:sid AND status='RUNNING' AND attempts=:my_attempt;
```

首次 AC 判定（与 finalize 在同一事务内）：

```text
UPDATE user_problem_stats
   SET solved=1, first_ac_at=NOW(3), first_ac_submission_id=:sid
 WHERE user_id=:uid AND problem_id=:pid AND solved=0;
-- 行数 = 1 → 首次 AC：事务提交后重算 score 并 ZADD ... GT
```

### 8.2 重试策略

| 异常类型 | 是否重试 | 说明 |
| --- | --- | --- |
| 容器启动失败、Docker 暂不可用 | 是，有限次数 | 属于基础设施瞬时错误（InfraError）。 |
| Redis 临时不可用 | 是，按退避 | 入队失败由补偿扫描兜底，注意避免重复入队的副作用（claim 已保证无害）。 |
| MySQL 暂时连接失败 | 是，有限次数 | 确保事务回滚；连接池使用 pool_pre_ping。 |
| Worker 崩溃 / lease 过期 | 是，由扫描器接管 | 不依赖任务自己重试（8.3）。 |
| 代码编译错误 | 否 | 属于用户提交问题。 |
| 答案错误 / 运行时错误 | 否 | 不属于系统级失败。 |
| 超时 / 内存超限 / 输出超限 | 否 | 判题本身完成了“超限”判定；不应无限重跑。 |

- 重试 = 把状态改回 QUEUED，并带退避重新入队。计数统一使用 attempts（每次 claim 加 1），上限初始建议 3；Celery 自身的 max_retries 不作为预算。

- 退避初始建议：第 1 次失败后约 5 s，第 2 次约 20 s，之后约 60 s。

- 次数用尽或不可重试的系统错误：RUNNING → FAILED，写入 error_code。

- 改回 QUEUED 与重新入队不是原子的；二者之间失败，由补偿扫描接管。

重试边界：　重试服务故障，不重试用户代码错误；所有重试必须有限次，并带退避策略。

### 8.3 补偿与崩溃恢复

所有恢复动作由 Celery Beat 触发，在 maintenance 队列执行。每个动作都是幂等的条件更新，即使扫描器重复执行、误起两个 Beat，也不会造成重复判题。

| 作业 | 周期 | 扫描条件 | 动作 |
| --- | --- | --- | --- |
| requeue_stale_queued | 30 s | status='QUEUED' AND queued_at &lt; NOW() - 阈值（初始建议 120 s），每次最多 100 条 | 条件更新 queued_at=NOW(), enqueue_count+1 成功后重新入队；enqueue_count 达到上限（初始建议 5）则标记 FAILED（ENQUEUE_EXHAUSTED）。 |
| recover_expired_running | 30 s | status='RUNNING' AND lease_expires_at &lt; NOW()，每次最多 100 条 | attempts 未达上限：条件更新回 QUEUED 并重新入队；达到上限：标记 FAILED（WORKER_LOST）。 |
| cleanup_orphans | 5 min | 带 oj.judge=1 标签的存活容器；超龄临时目录 | 强制删除容器与目录，见 7.5。 |
| rebuild_ranking | 每日低峰 + 管理员触发 | 全量读取 user_problem_stats | 写入临时 key 后 RENAME 原子替换（10.4）。 |
| refresh_ranking_user | 按需 | 首次 AC 后 ZADD 失败的用户 | 重新计算该用户 score 并 ZADD … GT，带重试。 |

阈值的取舍：　requeue_stale_queued 的阈值必须大于“正常排队时间”，否则队列积压时会产生大量重复消息；重复消息虽然无害（claim 保证只判一次），但会让队列膨胀。enqueue_count 上限用来在“Worker 长时间全部不可用”时让提交体面地失败，而不是永远 QUEUED。

### 8.4 Celery 配置基线

示意，非最终实现；数值为初始建议。

```python
# app/tasks/celery_app.py（节选）
from celery import Celery
from kombu import Queue
```

```text
celery_app = Celery("oj", broker=settings.CELERY_BROKER_URL)   # redis://redis:6379/0
celery_app.conf.update(
    task_acks_late=True,               # 执行完才确认：Worker 崩溃时消息可被重新投递
    task_reject_on_worker_lost=True,   # 子进程被杀时拒绝并重投，而不是丢弃
    worker_prefetch_multiplier=1,      # 不囤积任务，避免长任务阻塞其他判题
    task_ignore_result=True,           # 不用 result backend，状态以 MySQL 为准
    task_default_queue="judge",
    task_queues=(Queue("judge"), Queue("maintenance")),
    task_routes={"app.tasks.maintenance.*": {"queue": "maintenance"}},
    task_soft_time_limit=170, task_time_limit=180,   # 硬上限 ≥ 题目最坏耗时估算
    broker_transport_options={"visibility_timeout": 3600},  # 必须大于任务硬上限
    broker_connection_retry_on_startup=True,
    timezone="UTC",
)
```

| 配置 | 为什么这样设 |
| --- | --- |
| task_acks_late + task_reject_on_worker_lost | 默认在执行前就确认消息，Worker 一崩任务就丢；延迟确认让消息在崩溃后仍可被重新投递。 |
| worker_prefetch_multiplier = 1 | 默认会预取多条消息；判题任务很长，预取会让某个 Worker 囤积任务而别的 Worker 空闲。 |
| visibility_timeout &gt; 任务硬上限 | Redis broker 靠它决定“未确认消息多久后重新投递”；设得比任务时长还短，长任务会被重复投递给另一个 Worker。 |
| judge 与 maintenance 分队列 | 补偿与清理任务不能被积压的判题任务拖住。 |
| 不使用 result backend | 判题结果是业务事实，写 MySQL；避免第二份状态来源。 |
| 硬上限与题目限制挂钩 | 题目发布时估算最坏耗时 测试点数 × (时限 + 2 s) + 20 s（例如 50 个点、时限 1 s，约 170 s）；超过硬上限则拒绝发布并提示：减少测试点、降低时限，或提高硬上限并同步调大 visibility_timeout。 |

最终兜底靠 lease 扫描，而不是 broker：　即使 broker 的重投机制按预期工作，它也要等 visibility_timeout（初始建议 1 小时）才会生效；用户不可能等这么久。所以 Worker 崩溃后的快速恢复完全依赖 8.3 的 lease 扫描，broker 的重投只是“迟到的重复消息”，由 claim 的条件更新吸收。

Worker 启动参数（初始建议）：celery -A app.tasks.celery_app worker -Q judge --concurrency=2 --pool=prefork；maintenance 队列由另一个轻量进程消费；Beat 单独一个服务。

### 8.5 并发与故障场景推演

这张表是面试时最值得讲的部分：每个场景对应一个可以演示的故障演练（15.2）。

| # | 场景 | 会发生什么 | 结果 |
| --- | --- | --- | --- |
| 1 | broker 重复投递同一 submission_id | 第二个 Worker 的 claim 受影响行数为 0 | 直接结束，不重复判题 |
| 2 | Worker 在容器运行中被 kill -9 | lease 过期 → recover 扫描回到 QUEUED 并重新入队 → 重新判题；原消息在 visibility_timeout 后迟到，claim 失败 | 提交收敛到终态 |
| 3 | 旧 Worker 因 GC 暂停/网络分区后“复活”并回写 | finalize 的 attempts 围栏不匹配，行数为 0 | 丢弃过期结果并清理容器 |
| 4 | 提交事务已 COMMIT，但入队失败（Redis 抖动） | 用户已得到 202；阈值后 stale 扫描重新入队 | 提交被补偿，不会永远 QUEUED |
| 5 | 同一用户同时 AC 同一题两次 | solved=0 的条件更新只有一个事务得到行数 1 | 只计一次分、只更新一次榜单 |
| 6 | 同一用户同时首次 AC 两道不同题 | 两个 ZADD … GT 可能乱序到达 | 较小的分数被忽略，较大的保留 |
| 7 | Redis 重启且数据丢失（无持久化） | 队列消息丢失；缓存清空；榜单清空；限流计数清零 | QUEUED 被补偿；榜单重建；缓存回源；限流自然恢复 |
| 8 | MySQL 短暂断开 | 连接池 pool_pre_ping 重连；Worker 把它当作 InfraError 重试；API 返回 503 | 有限次重试后恢复 |
| 9 | 用户重复点击提交（同一个 Idempotency-Key） | (user_id, idempotency_key) 唯一冲突，读取原记录 | 返回同一个 submission_id |
| 10 | Docker daemon 不可用 | 容器创建失败 → InfraError → 退避重试 | attempts 用尽后 FAILED（INFRA_ERROR） |

## 9. 数据库设计

v1.1 变更｜新增 tags / problem_tags / user_problem_stats；submissions 增加 attempts、lease、时间点、联合唯一幂等键；test_cases 区分样例与隐藏；统一类型约定；给出核心表 DDL、索引驱动查询、造数与 EXPLAIN 方案、分析只读视图（I-01、I-02、I-08、I-10、I-14、I-15、I-23）。

### 9.1 总览与约定

[图4 Mermaid 单一来源](figures/er.md)（[v1.1 原图存档](figures/reference/er-v1.1.png)）

图 4  核心表关系（ER 图）

| 约定 | 取值 | 原因 |
| --- | --- | --- |
| 主键 | BIGINT UNSIGNED AUTO_INCREMENT | 统一；项目 ID 远小于 2^53，接口返回数字（2.4 决策 8）。 |
| 字符集 | utf8mb4，InnoDB | 支持中文与 emoji。 |
| 时间 | DATETIME(3)，存 UTC，展示时转换 | 毫秒精度便于计算排队与判题耗时。 |
| 枚举 | 用 VARCHAR + 应用层枚举，不用 MySQL ENUM | 状态值可读，便于迁移，也便于 NL2SQL 理解（9.7）。 |
| 外键 | 使用物理外键 | 演示规模下开销可忽略，换来完整性；数据量扩大 10 倍后，可在迁移中去掉 submissions 相关外键，改由应用层保证（面试可讲的取舍）。 |
| 软删除 | 不做；题目用 status=OFFLINE 下线 | 已有提交需要保留其题目与结果。 |
| 迁移 | Alembic，首版迁移就包含本章全部表 | 避免后续大改表。 |

### 9.2 表结构

#### 9.2.1 users 与 problems

```sql
CREATE TABLE users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(32)  NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          VARCHAR(16)  NOT NULL DEFAULT 'USER',     -- USER / ADMIN
  status        VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE / DISABLED
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```sql
CREATE TABLE problems (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  slug            VARCHAR(64)  NOT NULL,
  title           VARCHAR(128) NOT NULL,
  description     MEDIUMTEXT   NOT NULL,                  -- Markdown
  difficulty      VARCHAR(8)   NOT NULL,                  -- EASY / MEDIUM / HARD
  time_limit_ms   INT UNSIGNED NOT NULL DEFAULT 1000,
  memory_limit_mb INT UNSIGNED NOT NULL DEFAULT 256,
  status          VARCHAR(16)  NOT NULL DEFAULT 'DRAFT',  -- DRAFT / PUBLISHED / OFFLINE
  created_by      BIGINT UNSIGNED NOT NULL,
  created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_problems_slug (slug),
  KEY idx_problems_status_difficulty_id (status, difficulty, id),
  CONSTRAINT fk_problems_creator FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 9.2.2 test_cases

```sql
CREATE TABLE test_cases (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  problem_id      BIGINT UNSIGNED NOT NULL,
  case_index      INT UNSIGNED NOT NULL,
  is_sample       TINYINT(1)   NOT NULL DEFAULT 0,        -- 1 = 样例，可对外展示
  input_data      MEDIUMTEXT   NOT NULL,
  expected_output MEDIUMTEXT   NOT NULL,                  -- 永不进入判题容器
  input_size      INT UNSIGNED NOT NULL,
  output_size     INT UNSIGNED NOT NULL,
  sha256          CHAR(64)     NOT NULL,                  -- 便于校验与去重
  created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_cases_problem_idx (problem_id, case_index),
  CONSTRAINT fk_cases_problem FOREIGN KEY (problem_id) REFERENCES problems(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 9.2.3 submissions 与 submission_cases

```sql
CREATE TABLE submissions (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id          BIGINT UNSIGNED NOT NULL,
  problem_id       BIGINT UNSIGNED NOT NULL,
  language         VARCHAR(16)  NOT NULL,                 -- python / cpp
  code             TEXT         NOT NULL,                 -- ≤ 32 KB（应用层 + Nginx 限制）
  time_limit_ms_snapshot   INT UNSIGNED NOT NULL,         -- 本次判题使用的时间限制快照
  memory_limit_mb_snapshot INT UNSIGNED NOT NULL,         -- 本次判题使用的内存限制快照
  status           VARCHAR(20)  NOT NULL DEFAULT 'QUEUED',
  error_code       VARCHAR(32)  NULL,                     -- 仅 FAILED 使用
  error_message    VARCHAR(2048) NULL,                    -- 编译输出等，已截断
  passed_cases     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  total_cases      SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  runtime_ms       INT UNSIGNED NULL,
  memory_kb        INT UNSIGNED NULL,
  attempts         TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- 每次 claim +1，围栏与重试预算
  enqueue_count    TINYINT UNSIGNED NOT NULL DEFAULT 1,   -- 补偿入队次数
  worker_id        VARCHAR(64)  NULL,
  lease_expires_at DATETIME(3)  NULL,
  request_id       VARCHAR(64)  NOT NULL,                 -- API 请求追踪 ID，仅用于日志链路
  idempotency_key  VARCHAR(64)  NOT NULL,                 -- 客户端 Idempotency-Key，与追踪 ID 分离
  queued_at        DATETIME(3)  NOT NULL,                 -- 最近一次入队时间
  started_at       DATETIME(3)  NULL,
  finished_at      DATETIME(3)  NULL,
  created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_sub_user_idempotency (user_id, idempotency_key),
  KEY idx_sub_user_id (user_id, id),
  KEY idx_sub_user_problem_id (user_id, problem_id, id),
  KEY idx_sub_user_status (user_id, status),
  KEY idx_sub_status_queued (status, queued_at),
  KEY idx_sub_status_lease (status, lease_expires_at),
  KEY idx_sub_problem_status (problem_id, status),
  CONSTRAINT fk_sub_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_sub_problem FOREIGN KEY (problem_id) REFERENCES problems(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```sql
CREATE TABLE submission_cases (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  submission_id  BIGINT UNSIGNED NOT NULL,
  test_case_id   BIGINT UNSIGNED NULL,                    -- 测试点被删除后置空
  case_index     INT UNSIGNED NOT NULL,                   -- 快照
  is_sample      TINYINT(1)   NOT NULL,                   -- 快照
  status         VARCHAR(20)  NOT NULL,                   -- AC / WA / TLE / ...
  runtime_ms     INT UNSIGNED NULL,
  memory_kb      INT UNSIGNED NULL,
  stdout_snippet VARCHAR(1024) NULL,                      -- 仅“非 AC 的样例点”保存
  stderr_snippet VARCHAR(2048) NULL,                      -- 仅运行时错误保存，已截断
  UNIQUE KEY uk_sc_sub_idx (submission_id, case_index),
  CONSTRAINT fk_sc_sub  FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
  CONSTRAINT fk_sc_case FOREIGN KEY (test_case_id)  REFERENCES test_cases(id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 9.2.4 user_problem_stats、tags、problem_tags、audit_logs

```sql
CREATE TABLE user_problem_stats (
  user_id                BIGINT UNSIGNED NOT NULL,
  problem_id             BIGINT UNSIGNED NOT NULL,
  attempts               INT UNSIGNED NOT NULL DEFAULT 0,   -- 提交次数
  solved                 TINYINT(1)   NOT NULL DEFAULT 0,   -- 是否已首次 AC
  first_ac_at            DATETIME(3)  NULL,
  first_ac_submission_id BIGINT UNSIGNED NULL,
  updated_at             DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (user_id, problem_id),
  CONSTRAINT fk_ups_user    FOREIGN KEY (user_id)    REFERENCES users(id),
  CONSTRAINT fk_ups_problem FOREIGN KEY (problem_id) REFERENCES problems(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

| 表 | 用途 | 关键字段与约束 |
| --- | --- | --- |
| tags | 题目标签 | id、name（唯一）。 |
| problem_tags | 题目与标签多对多 | 联合主键 (problem_id, tag_id)，两个外键；tag_id 上另建索引服务“按标签筛选”。 |
| audit_logs | 管理审计日志 | id、user_id、action、resource_type、resource_id、payload_summary（摘要，不含完整数据）、request_id、ip、created_at；索引 (resource_type, resource_id, id) 与 (user_id, id)。 |

- submissions.score 已取消：v1.0 中它的含义不明；v1.1 用 passed_cases / total_cases 表达通过程度，不做部分得分。

- attempts 的两个含义：在 submissions 里是“第几次被 claim”（围栏与重试预算）；在 user_problem_stats 里是“该用户对该题的提交次数”。

- 修改测试数据不重判历史提交：submission_cases 保存 case_index 与 is_sample 的快照，测试点被删除时 test_case_id 置空，历史结果仍可读。

### 9.3 索引设计

每个索引都要能指出“它在服务哪条查询”；指出不了的索引不建。

| 索引 | 驱动查询 | 说明 |
| --- | --- | --- |
| users(username) 唯一 | 登录、注册查重 | — |
| problems(status, difficulty, id) | 题库分页：status='PUBLISHED' + 难度筛选 + 按 id 排序 | 题量不大，主要用于规范与面试说明，不作为优化重点。 |
| submissions(user_id, idempotency_key) 唯一 | 幂等兜底；重复提交时回读原记录 | 把“幂等”变成数据库约束，而不是约定。 |
| submissions(user_id, id) | 个人提交历史（游标分页，按 id 倒序） | id 自增，与时间同序；游标避免深翻页的大 OFFSET。 |
| submissions(user_id, problem_id, id) | 个人历史按题目筛选 | — |
| submissions(user_id, status) | 在途提交数：status IN ('QUEUED','RUNNING') | 在途集合极小，计数几乎是常数成本。 |
| submissions(status, queued_at) | 补偿扫描：长时间停留在 QUEUED 的记录 | status 区分度低，但被查询的取值（QUEUED）占比极小，索引依然高效。 |
| submissions(status, lease_expires_at) | 恢复扫描：lease 已过期的 RUNNING | 同上。 |
| submissions(problem_id, status) | 管理端按题目与状态筛选、题目维度统计 | — |
| submission_cases(submission_id, case_index) 唯一 | 一次提交的明细 | 同时防止同一测试点重复写入。 |
| user_problem_stats(user_id, problem_id) 主键 | 首次 AC 条件更新；用户通过题数统计 | 榜单重建全表扫描 solved=1，低频可接受。 |

### 9.4 EXPLAIN 验证方案

规划02 要求“针对提交记录或榜单查询设计联合索引，用 EXPLAIN 对优化前后进行对比”。要让对比有意义，需要先有足够的数据量。

- 造数：scripts/seed_data.py 生成 10³ 级用户、10² 级题目、10⁶ 级提交记录；终态分布与时间分布尽量接近真实（大部分为终态，少量 QUEUED/RUNNING）。造数脚本同时服务压测与 NL2SQL 评测。

- 选两条查询做对比：① 个人提交历史（user_id + 游标 + 可选 problem_id）；② 补偿扫描（status='QUEUED' AND queued_at &lt; ?）。

- 优化前：只保留主键与唯一索引，记录 EXPLAIN 的 type / key / rows / Extra 与实际耗时。

- 优化后：加入 9.3 的对应索引，重复测量；顺带对比 OFFSET 深翻页与游标分页。

- 记录：把前后对比写入 docs/evidence/mysql-explain.md（SQL、执行计划、实测耗时、结论）。简历中的优化数字只能来自这份记录。

面试验证点：　能讲清联合索引的最左前缀、覆盖索引与回表，以及为什么列表查询要显式选列、不读取 code 与输出字段。

### 9.5 大字段与数据上限

| 字段 | 上限（初始建议） | 限制手段 |
| --- | --- | --- |
| submissions.code | 32 KB | Nginx 请求体限制 + Pydantic 长度校验，两层都要有。 |
| test_cases.input_data / expected_output | 单点 ≤ 1 MB；每题 ≤ 50 个点 | 管理端接口校验；超大数据改走文件存储（19.2）。 |
| error_message（编译输出） | 2 KB | 写入前截断，并标注已截断。 |
| stdout_snippet / stderr_snippet | 1 KB / 2 KB | 仅非 AC 的样例点保存 stdout；仅运行时错误保存 stderr；AC 的测试点不保存任何输出。 |
| 提交列表查询 | — | 显式选列，不读取 code；详情页才读取。 |

### 9.6 迁移与数据保留

- Alembic 管理全部表结构；迁移是部署流程中的独立步骤（14.3），不在应用启动时隐式执行。

- MVP 不做 submissions 归档与分区；触发条件见 19.2。

- 备份与恢复见 14.5；Redis 中的数据全部可由 MySQL 重建，不单独备份。

### 9.7 分析只读视图（为项目二预留）

规划02 提到：OJ 的用户、题目、提交、运行时间等数据可以成为项目二 NL2SQL 的分析数据集。为此预留以下设计，避免日后返工：

- 只读数据库账户 oj_readonly：只授予视图的 SELECT，没有任何写权限，也看不到基础表。

- 分析视图：v_submission_facts（提交事实：用户、题目、语言、状态、通过用例数、排队耗时、判题耗时）、v_problem_stats（题目通过率与平均耗时）、v_user_stats（用户通过题数）。视图不包含 password_hash、code、测试数据与任何输出字段。

- 表与字段 COMMENT：为分析视图的每个字段写中文 COMMENT 与业务术语（如“在途提交”“首次 AC”），供 Schema 检索使用。

- 时间字段统一：全部 DATETIME(3)、UTC，便于直接计算排队时间与判题耗时。

- 造数脚本复用：同一份造数既用于 EXPLAIN 与压测，也用于 NL2SQL 评测集。

## 10. Redis 设计

v1.1 变更｜新增数据丢失后的恢复表、缓存三大问题与一致性边界、限流算法与阈值形态、排行榜 score 编码与重建、淘汰策略与隔离（I-01、I-11、I-12、I-13）。

### 10.1 职责边界与恢复

- MySQL 保存最终业务事实与可恢复数据。

- Redis 提升读写效率或承担短期状态，不作为唯一数据源。

- 缓存失效策略必须在题目更新、测试数据变化等时刻明确执行。

| Redis 中的数据 | 丢失后的后果 | 恢复手段 |
| --- | --- | --- |
| judge 队列消息 | 已入队但未被取走的任务消失 | stale 扫描会把仍是 QUEUED 的提交重新入队（8.3） |
| 排行榜 ZSET | 榜单为空或落后 | rebuild_ranking 从 user_problem_stats 整体重建 |
| 题目缓存 | 冷启动时请求回源 MySQL | 自动回填，无需人工处理 |
| 限流计数 | 窗口内计数清零 | 自然恢复；在途上限由 MySQL 兜底 |
| 分布式锁 | 缓存重建互斥短暂失效 | TTL 过期自动恢复；最坏情况是多次回源 |

### 10.2 缓存设计

| Key | 结构 | TTL | 说明 |
| --- | --- | --- | --- |
| oj:problem:{id} | String/JSON | 10 min ± 抖动 | 题目对外 DTO（只含样例，不含隐藏用例）。 |
| oj:problem:{id}（空值） | String | 60 s | 不存在的题目缓存占位 __NULL__，防穿透。 |
| oj:problems:ver | String | 无 | 题库版本号；任何题目写操作 INCR。 |
| oj:problems:list:{ver}:{page}:{size}:{difficulty}:{tag} | String/JSON | 60 s | 列表缓存；版本号变化即整体失效，不做逐键删除。 |
| oj:lock:problem:{id} | String | 10 s | 热点缓存重建互斥（SET NX EX）。 |

#### 缓存三大问题与一致性

| 问题 | 处理 |
| --- | --- |
| 穿透（查不存在的数据） | 题目 ID 先做格式校验；不存在则写入短 TTL 的空值标记，避免每次都打到 MySQL。 |
| 击穿（热点 key 过期瞬间） | 回源前 SET NX 抢重建锁；抢不到的请求短暂等待后重读缓存，仍无则放行回源一次。 |
| 雪崩（大量 key 同时过期） | TTL 加随机抖动；列表缓存 TTL 短且靠版本号失效，避免集中过期。 |
| 一致性 | Cache-Aside：先更新 MySQL，再删除缓存（并 INCR 版本号）。最大陈旧时间以 TTL 兜底；明确承诺“最终一致”，不承诺强一致。 |
| 不缓存的数据 | 提交详情与状态（实时性要求高）、个人数据、管理端数据、任何含隐藏测试数据的内容。 |

### 10.3 限流

- 算法：MVP 使用固定窗口计数，用 Lua 脚本保证 INCR 与 EXPIRE 的原子性；滑动窗口留作 M4 的可对比实验，不预先实现。

- 在途上限：每个用户在途提交数（QUEUED + RUNNING）不超过上限（初始建议 3），查询走索引 (user_id, status)。这是软限制：并发下可能多放过一两个，可以接受。

- 响应：超限返回 429，带 Retry-After，错误码区分 RATE_LIMITED 与 TOO_MANY_INFLIGHT。

- 降级：Redis 不可用时，查询类与登录接口放行并记录告警日志；提交接口放行，但仍受 MySQL 在途上限约束。这是已接受的降级：Redis 同时是 broker，它不可用时系统本就处于故障状态，重点是尽快恢复而不是在此时拒绝所有请求。

| 场景 | 维度 | 初始阈值（建议） | 说明 |
| --- | --- | --- | --- |
| 登录失败 | IP + 用户名 | 5 次 / 分钟 | 同时返回一致的错误信息，防枚举。 |
| 注册 | IP | 5 次 / 小时 | 防批量注册。 |
| 提交代码 | 用户 | 10 次 / 分钟；在途 ≤ 3 | 防灌队列。 |
| 查询类 | 用户或 IP | 60 次 / 分钟 | 匿名按 IP。 |
| Nginx 层 | IP | 粗粒度 limit_req | 挡住最粗暴的洪泛，细粒度交给应用。 |

限流 Lua 脚本（示意，非最终实现）：

```lua
-- KEYS[1]=计数键  ARGV[1]=窗口秒数  ARGV[2]=阈值
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
if n > tonumber(ARGV[2]) then
  return {0, redis.call('TTL', KEYS[1])}   -- 拒绝，并返回剩余秒数
end
return {1, 0}
```

限流键：oj:ratelimit:{scope}:{id}:{window_start}，TTL 等于窗口长度。阈值全部是初始建议，压测后校准。

### 10.4 排行榜

| 项 | 设计 |
| --- | --- |
| Key | oj:ranking:total（ZSET）；member = user_id；无 TTL。 |
| 排行规则 | 通过题数多者在前；同题数时，“最后一次首次通过的时间”早者在前。 |
| score 编码 | score = 通过题数 × 10¹⁰ + (10¹⁰ − 最后一次首次通过的 Unix 秒时间戳)。10¹⁰ 大于任何时间戳，所以题数始终优先；同题数时越早完成 score 越大。double 可精确表示的整数上限约 9×10¹⁵，通过题数在 10⁵ 以内都是安全的。 |
| 首次 AC 判定 | 在 finalize 事务内对 user_problem_stats 做 WHERE solved=0 的条件更新，行数为 1 才算（8.1）。 |
| 更新流程 | 事务提交之后查询 COUNT(*) 与 MAX(first_ac_at)（solved=1）重新计算 score，执行 ZADD oj:ranking:total GT {score} {user_id}。 |
| 为什么用 GT | 同一用户的不同题目可能乱序提交写入；通过题数只增不减，score 单调不减，GT 让“较小的旧分数”无法覆盖“较大的新分数”，写入既幂等又抗乱序。不用 ZINCRBY，因为它不幂等。 |
| 写失败 | ZADD 失败不影响判题结果；登记 refresh_ranking_user（带重试），并由每日重建兜底。 |
| 整体重建 | 全量读取 user_problem_stats 计算 score，写入 oj:ranking:total:tmp，完成后 RENAME 原子替换；管理员可手动触发。 |
| 读取 | Top N：ZREVRANGE … WITHSCORES，再用一次批量查询（IN）补用户名；个人名次：ZREVRANK + 1，不在榜上则显示“未上榜”。 |

### 10.5 淘汰策略与隔离

- 单实例，maxmemory-policy noeviction：Celery 的队列键一旦被淘汰就会丢任务，所以不使用任何 allkeys-* 或 volatile-* 淘汰策略；内存满时写入报错，由告警暴露问题。

- 缓存键必带 TTL，且总量可控（题目只有 10² 级）；设置 maxmemory（初始建议 128 MB）与使用率告警。

- 逻辑库隔离：Celery 使用 db0，缓存/排行榜/限流/锁使用 db1。这只是命名隔离，淘汰策略与内存仍是实例级；若压测发现缓存与队列相互影响，再拆成两个实例（ADR-012）。

- 持久化：因为数据均可重建，MVP 可选开启 AOF everysec 以减少重启后的补偿工作量，不强求。

- 访问控制：requirepass，仅在内部网络监听，不映射宿主机端口。

## 11. API 设计

v1.1 变更｜接口由 10 个补全到 30 个并按“公开 / 用户 / 管理员 / 运维”分组；管理接口统一 /api/v1/admin 前缀；新增统一错误体、分页约定、状态码语义；Idempotency-Key 必填；新增结果脱敏规则（I-08、I-09）。

以下接口形成 MVP 的稳定边界。OpenAPI、代码与本设计不一致时先停止并报告，由用户确认后再同步变更；不能以“OpenAPI 为准”默改设计。

### 11.1 通用约定

| 项 | 约定 |
| --- | --- |
| 路径与版本 | 统一前缀 /api/v1；JSON 请求与响应，UTF-8；Swagger/OpenAPI 在 /docs（生产环境可限制访问）。 |
| 认证 | Authorization: Bearer &lt;JWT&gt;。匿名可读的接口在表格中标注“公开”。 |
| ID | 数字（BIGINT）；本项目 ID 远小于 2^53。访问控制靠归属校验：访问不属于自己的提交返回 404，避免被枚举。 |
| 时间 | ISO 8601，UTC，毫秒精度，如 2026-10-09T08:00:00.123Z。 |
| 分页 | 题库、管理端列表用页码：page、size（size ≤ 50）；提交历史与后台提交列表用游标：cursor、limit，响应返回 next_cursor（无更多数据时为 null）。 |
| 请求追踪 | 每个响应带 X-Request-ID；客户端可传入，服务端缺省则生成。request_id 只用于请求追踪；Idempotency-Key 独立存为 idempotency_key，二者不混用。 |
| 限流响应 | 429，带 Retry-After 秒数。 |

#### 统一错误体与状态码

```text
{
  "error": {
    "code": "TOO_MANY_INFLIGHT",
    "message": "当前有 3 个提交仍在判题，请稍后再试",
    "request_id": "7f3c0d9e5a1b4c2f"
  }
}
```

| 状态码 | 错误码示例 | 含义 |
| --- | --- | --- |
| 401 | UNAUTHENTICATED | 未登录、token 无效或过期。 |
| 403 | FORBIDDEN | 已登录但无权限（如普通用户访问 /admin）；账号被禁用。 |
| 404 | NOT_FOUND | 资源不存在，或不属于当前用户（刻意不区分）。 |
| 409 | CONFLICT | 唯一约束冲突（用户名、slug）；题目状态不允许当前操作。 |
| 413 | PAYLOAD_TOO_LARGE | 请求体超过限制（代码、测试数据）。 |
| 422 | VALIDATION_ERROR | 参数校验失败（沿用 FastAPI 默认的 422），message 说明字段。 |
| 429 | RATE_LIMITED / TOO_MANY_INFLIGHT | 触发限流或在途提交上限。 |
| 503 | SERVICE_UNAVAILABLE | 依赖暂时不可用（数据库、Redis）；可重试。 |

### 11.2 认证接口

| 方法 | 路径 | 用途 | 权限 |
| --- | --- | --- | --- |
| POST | /api/v1/auth/register | 注册；用户名唯一，密码长度与强度校验 | 公开（IP 限流） |
| POST | /api/v1/auth/login | 登录并获取 JWT；失败信息统一 | 公开（失败限流） |
| GET | /api/v1/auth/me | 当前用户信息（角色、状态） | 用户 |

MVP 不提供服务端登出与 refresh：登出由前端丢弃 token 完成，access token 有效期短（12.2）。

初始管理员通过一次性命令创建，不通过迁移预置密码；普通注册接口不接受管理员角色。创建命令的核心权限、哈希及事务逻辑由用户编写并验收（见 6.1、14.3）。

### 11.3 题库接口

| 方法 | 路径 | 用途 | 权限 |
| --- | --- | --- | --- |
| GET | /api/v1/problems | 已发布题目分页；支持难度、标签、关键字筛选 | 公开 |
| GET | /api/v1/problems/{id} | 题目详情（题面、限制、仅样例用例、标签） | 公开 |

公开接口的可见范围由 2.4 决策 1 决定；若改为“全部需要登录”，只需把权限列改为“用户”。

### 11.4 提交与排行榜接口

| 方法 | 路径 | 用途 | 权限 |
| --- | --- | --- | --- |
| POST | /api/v1/submissions | 创建提交并入队；返回 202 | 用户 |
| GET | /api/v1/submissions/{id} | 查看提交状态与结果 | 提交者 / 管理员 |
| GET | /api/v1/submissions | 个人提交历史（游标分页；problem_id、status 可选） | 用户 |
| GET | /api/v1/rankings | 排行榜 Top N（limit ≤ 100） | 公开 |
| GET | /api/v1/rankings/me | 当前用户的名次、通过题数 | 用户 |

#### 11.4.1 POST /submissions

```http
POST /api/v1/submissions
Authorization: Bearer <JWT>
Idempotency-Key: 5b0d7a3e-4c1f-4f6a-9d52-1e8c2a7b9f40     # 必填，16–64 个字符
```

```text
{
  "problem_id": 1001,
  "language": "python",
  "code": "print(sum(map(int, input().split())))"
}
```

```http
HTTP/1.1 202 Accepted
{
  "submission_id": 90817,
  "status": "QUEUED"
}
```

- 幂等：同一用户的同一个 Idempotency-Key 重复提交，返回原来的 submission_id（同样是 202），并带响应头 Idempotent-Replayed: true；请求体差异被忽略，同一个 key 视为同一次提交。

- 校验顺序：鉴权 → 限流 → 参数校验（题目已发布、语言受支持、代码长度）→ 在途上限；对应错误码依次为 401 / 429 / 422 / 429。

- 404 vs 422：题目不存在或未发布，返回 422 VALIDATION_ERROR（problem_id 字段），不暴露草稿题目的存在。

#### 11.4.2 GET /submissions/{id}

```http
HTTP/1.1 200 OK
{
  "submission_id": 90817,
  "problem_id": 1001,
  "language": "python",
  "status": "WRONG_ANSWER",
  "passed_cases": 2,
  "total_cases": 7,
  "runtime_ms": 18,
  "memory_kb": 9216,
  "queued_ms": 420,          # 排队耗时 = started_at - queued_at
  "judged_ms": 1130,         # 判题耗时 = finished_at - started_at
  "created_at": "2026-10-09T08:00:00.123Z",
  "cases": [
    {"index": 1, "status": "AC", "runtime_ms": 12, "is_sample": true},
    {"index": 2, "status": "AC", "runtime_ms": 14, "is_sample": false},
    {"index": 3, "status": "WA", "runtime_ms": 18, "is_sample": false}
  ]
}
```

code 字段只在详情接口中返回，且只给提交者与管理员；历史列表不返回。非终态时，cases 为空，finished_at 与耗时字段为 null。

### 11.5 结果可见性与脱敏

为什么单独成节：　如果结果页回显了隐藏用例的输入、期望输出或实际输出，用户就能把完整测试集拼出来，判题就失去意义。下面的规则必须同时落实在接口序列化、缓存内容、日志三处。

| 内容 | 提交者 | 管理员 | 其他人 |
| --- | --- | --- | --- |
| 提交状态、通过用例数、总耗时与内存 | 可见 | 可见 | 不可见（404） |
| 每个测试点的序号、结论、耗时 | 可见 | 可见 | 不可见 |
| 样例测试点的输入 / 期望输出 / 实际输出（非 AC 时） | 可见 | 可见 | 不可见 |
| 隐藏测试点的输入 / 期望输出 / 实际输出 | 不可见 | 仅测试数据管理接口可见 | 不可见 |
| 运行时错误的 stderr（截断后） | 仅样例点可见；隐藏点不可见 | 仅样例点可见；隐藏点不可见 | 不可见 |
| 编译输出（截断后） | 可见 | 可见 | 不可见 |
| 提交的源代码 | 可见 | 可见 | 不可见 |

- 对外题目 DTO 只包含样例用例；缓存只存对外 DTO（10.2）。

- 隐藏测试点结果采用字段白名单，只回状态、耗时、内存，不回用户程序的 stdout/stderr。此规则覆盖提交者与管理员的判题结果接口，也覆盖汇总 error_message 等出口；测试数据管理接口的既有权限边界不变。样例点输出和编译输出可按既有上限截断后回传。

- 日志里不打印测试数据与用户代码，只打印长度、哈希与 ID。

- 接口测试必须覆盖：用一个非管理员账号请求所有接口，断言响应与缓存中都不含隐藏用例内容（15.1）。

### 11.6 管理接口（/api/v1/admin）

管理员接口统一放在 /api/v1/admin 下，由同一个依赖项做角色校验，所有写操作都会写入审计日志。


测试点增删改及限制修改：题目存在 QUEUED/RUNNING 提交时拒绝，沿用 409 CONFLICT；提交接收与编辑操作须在事务协调下维持该约束，具体锁定方案由用户在 M1 确认。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /admin/problems | 创建题目（草稿） |
| GET | /admin/problems | 题目列表（含草稿与下线） |
| GET | /admin/problems/{id} | 题目管理详情 |
| PUT | /admin/problems/{id} | 修改题目；成功后使缓存失效 |
| POST | /admin/problems/{id}/publish | 发布：校验至少 1 个测试点、至少 1 个样例、时间预算在硬上限内 |
| POST | /admin/problems/{id}/offline | 下线；已有提交保持可见 |
| GET | /admin/problems/{id}/test-cases | 测试点列表（含隐藏用例内容） |
| POST | /admin/problems/{id}/test-cases | 新增测试点；校验大小上限 |
| PUT | /admin/test-cases/{id} | 修改测试点（含 is_sample） |
| DELETE | /admin/test-cases/{id} | 删除测试点；历史结果的 test_case_id 置空 |
| GET | /admin/tags | 标签列表 |
| POST | /admin/tags | 创建标签 |
| GET | /admin/users | 用户列表（分页，可按用户名搜索） |
| PATCH | /admin/users/{id} | 修改角色或状态（启用/禁用） |
| GET | /admin/submissions | 全部提交记录（游标分页；用户、题目、状态筛选） |
| GET | /admin/audit-logs | 审计日志（游标分页） |
| GET | /admin/stats/queue | 队列长度、在途数量、QUEUED/RUNNING 计数、最老 QUEUED 的等待时长 |
| POST | /admin/rankings/rebuild | 触发榜单重建（异步，返回 202） |

### 11.7 运维接口

| 方法 | 路径 | 用途 | 权限 |
| --- | --- | --- | --- |
| GET | /healthz | 存活检查：进程在运行即返回 200，不检查依赖 | 公开（仅内网） |
| GET | /readyz | 就绪检查：检查 MySQL 与 Redis 可用；任一不可用返回 503 | 公开（仅内网） |

接口总数：认证 3 + 题库 2 + 提交与榜单 5 + 管理 18 + 运维 2 = 30。运维接口由 Nginx 限制为仅内网访问（Compose 的健康检查与外部探活使用）。

## 12. 安全设计

v1.1 变更｜新增认证与会话细则、测试数据保护、输入与资源限制、密钥与配置；风险表补充 5 项；残余风险明确声明（I-08、I-16、I-21）。

### 12.1 风险与控制

| 风险 | 控制措施 | 优先级 |
| --- | --- | --- |
| 未授权访问 | JWT + RBAC + 资源归属校验；角色与状态以数据库为准 | P0 |
| 代码执行越权 | Docker 隔离、资源限制、无宿主机敏感挂载、关闭网络、丢弃 capability（7.2） | P0 |
| 测试数据泄露 | 期望输出不进容器；对外 DTO 与缓存不含隐藏用例；结果脱敏（11.5） | P0 |
| Worker 被攻破 | Worker 不对外暴露端口、不与公网服务同容器；限制 Docker API 调用范围；残余风险声明（7.6） | P0 |
| 恶意输出洪泛 | ulimit fsize、输出上限判 OUTPUT_LIMIT、日志截断 | P0 |
| 重复提交与重复计分 | 幂等键 + 状态条件更新 + 首次 AC 条件更新（8.1） | P0 |
| 接口刷爆与队列灌满 | 用户/IP 限流 + 在途提交上限（10.3） | P0 |
| 登录爆破与用户枚举 | 按 IP + 用户名限制失败次数；统一错误信息；强哈希 | P0 |
| SQL 注入 | SQLAlchemy 参数化查询；禁止拼接不可信 SQL | P0 |
| XSS | 题面 Markdown 净化；判题输出转义渲染；CSP（13.3） | P0 |
| 敏感信息泄漏 | 环境变量管理 Secret；日志不打印密码、Token、完整代码与测试数据 | P0 |
| 数据库/Redis 暴露公网 | 只在内部网络监听；安全组只放行 80/443；Redis 设密码（14.6） | P0 |
| 依赖与镜像漏洞 | 依赖锁定；定期运行 pip-audit 与 npm audit；及时更新基础镜像 | P1 |
| 后台误操作 | RBAC + 审计日志；发布前校验 | P1 |
| 安全边界：　该项目的目标是具备合理的公开环境防护，而不是宣称达到成熟 OJ 平台或专业沙箱产品的安全等级。 |  |  |

### 12.2 认证与会话

| 主题 | 决策 |
| --- | --- |
| 密码存储 | argon2id（或 bcrypt）加盐哈希；设置最小长度；绝不记录明文；哈希在线程池执行（4.4）。 |
| JWT | HS256；解码时显式指定算法白名单；密钥来自环境变量、足够长；payload 只放 sub、iat、exp。 |
| 有效期 | access token 短有效期（初始建议 30–60 分钟）；MVP 不做 refresh 与吊销黑名单（2.4 决策 7）。 |
| 角色与状态 | token 只作身份标识；每次鉴权按 sub 对应的用户主键查询角色与账号状态，不缓存二者；禁用账号、降权立即生效，不必等 token 过期。未来缓存必须先有压测证据及新 ADR。 |
| 登录防枚举 | 用户名不存在与密码错误返回同样的信息与相近的耗时；失败次数按 IP + 用户名限制（10.3）。 |
| Token 存放 | access token 存浏览器 localStorage（实现简单），以 XSS 防护作为主要缓解；httpOnly Cookie + CSRF Token 方案列入 19.2 备选。 |
| CORS | 生产环境前后端同源（经 Nginx），无需开放 CORS；开发环境用 Vite 代理，必要时使用白名单。 |

### 12.3 测试数据保护

- 隔离：期望输出只在 Worker 进程内与判题结果比对，永不写入工作目录、永不挂载进容器。

- 序列化边界：对外 DTO 的字段白名单里没有隐藏用例；管理接口使用独立的 Schema；单元测试断言对外 DTO 序列化后不含隐藏用例。

隐藏输出边界：隐藏点 stdout/stderr 不进入任何判题结果响应或日志；即使用户程序把输入写入 stderr 后异常退出，也只能返回该点状态、耗时、内存。样例与编译输出继续按既有截断规则处理。内部保存策略不在本次修订中扩展。

- 缓存边界：Redis 缓存只存对外 DTO；测试数据不缓存。

- 日志边界：不打印测试数据与用户代码，只记录大小、sha256 与 ID。

- 判题环境：输出目录每个测试点独立，用户程序无法读到别的测试点的输入或输出。

### 12.4 输入与资源限制

| 对象 | 限制（初始建议） | 位置 |
| --- | --- | --- |
| 普通接口请求体 | ≤ 256 KB | Nginx client_max_body_size（按 location 配置）+ Pydantic |
| 管理端测试数据上传 | ≤ 16 MB | 仅 /api/v1/admin/ 路径放宽，其他路径保持严格 |
| 提交代码 | ≤ 32 KB | Nginx + Pydantic，两层都要有 |
| 分页大小 | size ≤ 50；limit ≤ 100 | 接口校验 |
| 并发连接 / 请求频率 | 粗粒度限制 | Nginx limit_conn / limit_req |

### 12.5 密钥与配置

- 所有 Secret（数据库密码、JWT 密钥、Redis 密码）通过环境变量或 .env 注入；.env 加入 .gitignore，仓库只提交 .env.example。

- GitHub Actions 的密钥使用仓库 Secrets，不写入工作流文件。

- 数据库账户最小权限：应用账户（读写业务表）、迁移账户（DDL）、分析账户（oj_readonly，只读视图，9.7）。

- 日志不打印 Authorization 头、密码、Token。

## 13. 前端设计

v1.1 变更｜页面表增加注册页与路由守卫说明；新增 13.2 提交结果交互与 13.3 前端安全（I-16）。

### 13.1 页面

截至 2026-12-15 简历 v1，只保证三组页面：① 登录；② 题库与题目详情（含 Monaco 提交）；③ 结果与历史。榜单页、管理端页面后置；管理员先通过 Swagger 操作。表中其他页面保留为后续目标，不改变后端接口的 P0/P1。

| 页面 | 核心功能 |
| --- | --- |
| 登录 / 注册页 | 账号登录与注册、错误提示、Token 保存；登录失败被限流时给出明确提示。 |
| 题库页 | 分页、难度/标签筛选、题目搜索。 |
| 题目详情页 | 题目描述、约束、样例、Monaco Editor、语言选择与模板、提交按钮；提交按钮在请求期间禁用，并自动生成 Idempotency-Key。 |
| 提交详情页 | 状态、Verdict、运行时间、内存、错误输出、测试点明细；非终态时自动轮询（13.2）。 |
| 提交历史页 | 按题目/状态筛选，游标分页（“加载更多”）。 |
| 排行榜页 | Top N、个人名次、通过题数。 |
| 管理端 | 题目 CRUD 与发布/下线、测试数据管理（标注样例/隐藏）、标签、用户、提交记录、审计日志、队列状态面板。 |

### 13.2 提交结果交互

- 提交后跳转到提交详情页，按 1 s → 2 s → 3 s → 5 s 的节奏轮询；进入终态即停止；页面不可见时暂停，重新可见时立即刷新一次。

- QUEUED 超过 30 s 提示“排队较久，系统仍在处理”，避免重复提交；FAILED 时提示“系统异常，可以重新提交”。

- 429 响应显示 Retry-After 倒计时，不自动重试。

- 编辑器草稿按“用户 + 题目 + 语言”保存在 localStorage，提交成功后清除；读取失败时降级为空白。

### 13.3 前端安全

- Markdown 渲染：题面用 Markdown 渲染库解析后，再经 DOMPurify 之类的净化器处理；禁止渲染原始 HTML 与 javascript: 链接。

- 判题输出：编译输出、stderr、stdout 一律作为纯文本放入 &lt;pre&gt;（框架默认转义），不使用 v-html。

- CSP：Nginx 返回 Content-Security-Policy，限制脚本只能来自同源。

- 路由守卫只是体验层，不是安全控制；任何权限都以后端为准。

- Token：保存在 localStorage（12.2 的取舍），退出登录或收到 401 时清除。

前端定位：Vue3 + TypeScript 先交付 13.1 约定的三组页面；榜单与管理界面后置，管理能力先用 Swagger 验收，不挤占 12 月压测和故障演练窗口。

## 14. 部署与运维

v1.1 变更｜新增 beat 与迁移服务、网络分区与 docker.sock 挂载说明；新增迁移流程、可观测性规范、备份恢复、上线检查清单与内存预算（I-05、I-18、I-21）。

### 14.1 Compose 服务划分

本节为目标部署结构。阶段06开发环境只用 Compose 启动 MySQL 与 Redis，API 在 WSL 本地运行；阶段06不做 API 容器化。Dockerfile.dev 与可信 Worker 环境探针位于阶段06末尾、限时半天，仅用于环境验收，不实现生产判题器。

| 服务 | 作用 | 要点 |
| --- | --- | --- |
| nginx | 反向代理、静态资源、HTTPS 入口 | 唯一对外发布端口（80/443）；限制请求体；设置 CSP；运维接口仅内网。 |
| api | FastAPI 应用 | 2 个 worker 进程；不挂载 docker.sock；有 healthcheck。 |
| worker | Celery Worker（judge 队列） | 挂载 docker.sock；挂载与宿主机同路径的 judge 工作目录；并发度 2；不暴露端口。 |
| worker-maint | Celery Worker（maintenance 队列） | 轻量，并发度 1；需要 docker.sock（清理孤儿容器）；可与 beat 放在同一容器内以节省内存（二者都只能运行一个实例）。 |
| beat | Celery Beat | 只运行一个实例。 |
| migrate | 一次性任务：alembic upgrade head | api 与 worker 依赖它成功完成后启动。 |
| mysql | 业务数据库 | 数据卷；innodb_buffer_pool_size 按内存预算设置；只在内部网络监听。 |
| redis | 队列、缓存、排行榜、限流 | requirepass、noeviction、maxmemory；只在内部网络监听。 |

- 网络：edge（nginx ↔ api）与 backend（api、worker、beat、mysql、redis）两个网络；mysql 与 redis 不加入 edge。

- 卷：mysql_data、redis_data（可选）、judge 工作目录（宿主机路径与 Worker 容器内路径一致，4.3）。

- 依赖顺序：用 healthcheck + depends_on: condition: service_healthy 保证 mysql/redis 就绪后再启动应用，而不是靠 sleep。

- 资源限制：为每个服务设置内存上限，防止一个服务拖垮整机（14.6）。

### 14.2 环境配置

```dotenv
# 数据与队列
DATABASE_URL=mysql+asyncmy://oj_app:***@mysql:3306/oj
DATABASE_URL_SYNC=mysql+pymysql://oj_app:***@mysql:3306/oj
REDIS_URL=redis://:***@redis:6379/1
CELERY_BROKER_URL=redis://:***@redis:6379/0
```

```text
# 安全
JWT_SECRET=***                 # 足够长的随机串，仅来自环境变量
JWT_EXPIRE_MINUTES=60
```

```text
# 判题
JUDGE_IMAGE_PYTHON=oj-judge-python:1
JUDGE_IMAGE_CPP=oj-judge-cpp:1
JUDGE_WORK_DIR=/var/oj/judge-work     # 宿主机与 Worker 容器内路径一致
JUDGE_LEASE_SECONDS=60
JUDGE_MAX_ATTEMPTS=3
```

```text
# 运行
LOG_LEVEL=INFO
```

### 14.3 数据库迁移与发布流程

- 构建镜像（api、worker 共用后端镜像）与前端静态资源。

- 启动 migrate 一次性任务执行 alembic upgrade head；失败则中止发布。

- 迁移成功后启动 api、worker、beat；healthcheck 通过后 nginx 才接流量。

- 发布后冒烟：登录 → 提交一份已知答案 → 等待 ACCEPTED → 查看排行榜。

首次部署在迁移完成后执行一次性管理员创建命令；密码通过环境变量或隐藏输入读取，不写入迁移、源码、命令行参数或日志。

- 回滚：保留上一版镜像标签；涉及不可逆迁移的发布，先做数据库备份（14.5）。

MVP 允许发布期间短暂停机，不追求零停机发布。

### 14.4 日志与可观测性

#### 日志规范

- JSON 日志，固定字段：ts、level、service、request_id、user_id、submission_id、task_id、attempt、event、duration_ms。

- X-Request-ID 中间件把 request_id 放入 contextvars；提交入队时把它放进任务参数，让 API 与 Worker 的日志可以串起来。补偿投递可读取提交保存的追踪 ID；唯一幂等约束使用独立的 idempotency_key，不使用 request_id。

- API 与 Worker 日志分开输出，均可按 submission_id 检索。

| 事件（event） | 产生位置 | 用途 |
| --- | --- | --- |
| submission.created | API | 记录创建与幂等重放 |
| task.enqueued / enqueue.compensated | API / 维护任务 | 入队与补偿入队 |
| task.claimed / task.claim_lost | Worker | 领取成功 / 被他人处理 |
| container.started / container.finished | Worker | 每个测试点的容器生命周期与耗时 |
| verdict.final | Worker | 最终结论、通过用例数、耗时 |
| task.retry / lease.expired / task.failed | Worker / 维护任务 | 重试、租约过期、最终失败 |
| finalize.fenced | Worker | 过期 Worker 回写被围栏拒绝 |

#### 耗时与队列指标

- 排队耗时 = started_at − queued_at；判题耗时 = finished_at − started_at；端到端时延 = finished_at − created_at。三者都能从 MySQL 的三个时间点直接算出，压测报告据此区分。

- GET /admin/stats/queue 返回队列长度（LLEN judge）、QUEUED / RUNNING 计数与最老 QUEUED 的等待时长，管理端展示为一个简单面板。

- 不引入 Prometheus / Grafana / Langfuse 等；需要时再说明触发条件（19.2）。

### 14.5 备份与恢复

- MySQL：每日 mysqldump（或 mysqlpump）定时备份，保留 7 天；备份文件不放在数据库同一块盘上。

- 恢复演练：上线前至少做一次“从备份恢复到新库并启动系统”的演练，并把步骤写入 README；没有演练过的备份不算备份。

- Redis：数据均可重建，不单独备份；可选开启 AOF everysec 减少重启后的补偿工作量。

- 失败任务告警：FAILED 提交数量在窗口内超过阈值时，在管理端面板标红并写 ERROR 日志；MVP 不接外部告警渠道。

### 14.6 上线检查清单与内存预算

#### 上线检查清单

| 类别 | 检查项 |
| --- | --- |
| 网络与暴露面 | 云安全组只放行 80/443（SSH 仅限固定 IP）；MySQL、Redis 无公网端口；Worker 不发布端口。 |
| 域名与 HTTPS | 域名与 HTTPS 证书就绪；域名备案与相关要求以阿里云当前规定为准，尽早确认，避免临近投递才发现来不及。 |
| 密钥 | JWT 密钥、数据库与 Redis 密码已更换为强随机值；仓库中无明文 Secret。 |
| 判题 | 判题镜像已预先构建；沙箱样例集（15.2）全部通过；docker.sock 仅挂载给 Worker。 |
| 数据与备份 | 迁移已执行；备份任务已配置；恢复演练已完成。 |
| 日志与磁盘 | Docker 日志驱动设置 max-size / max-file；磁盘使用率有检查；docker system prune 不自动执行。 |
| 系统 | 服务器时间同步；基础镜像与系统补丁已更新；容器 restart: unless-stopped。 |
| 演示 | README 提供演示账号、一键启动步骤、设计取舍与已知限制。 |

#### 内存预算（2 vCPU / 4 GB，估算，实测校准）

| 组件 | 预算 | 说明 |
| --- | --- | --- |
| MySQL | ≈ 700 MB | innodb_buffer_pool_size 约 256 MB，其余为连接与内部缓冲。 |
| Redis | ≈ 150 MB | maxmemory 128 MB。 |
| API（2 个进程） | ≈ 250 MB | 每进程约 120 MB。 |
| Worker（并发 2）+ maintenance + beat | ≈ 400 MB | 含 Docker SDK 与数据库连接。 |
| Nginx | ≈ 30 MB | — |
| 判题容器（同时 2 个） | ≈ 640 MB | 每个：题目限制 256 MB + 64 MB 余量；峰值预算。 |
| 操作系统与缓存 | ≈ 500 MB | — |
| 合计 | ≈ 2.7 GB | 留有约 1.3 GB 余量；若压测发现不足，先降低 Worker 并发或判题内存上限。 |

## 15. 测试与压测

v1.1 变更｜新增判题与沙箱样例集、故障演练清单；压测方案补齐场景、数据量、指标口径与报告模板；新增 CI（GitHub Actions）（I-19、I-22）。

### 15.1 测试层级

测试隔离：纯 API 测试可使用事务回滚 fixture；涉及 Worker、独立进程或并发的测试使用独立测试数据库，并在测试边界清表，不能仅依赖单连接的外层事务回滚。

| 层级 | 测试内容 | 工具/手段 |
| --- | --- | --- |
| Unit | 状态转换（claim / finalize / 围栏）、比对器、Verdict 映射、幂等逻辑、score 编码、限流脚本 | Pytest；判题执行器用假的 DockerRunner |
| API | 认证、题库、提交、权限、分页、统一错误体、对外 DTO 不含隐藏用例 | Pytest + TestClient/httpx |
| Integration | API → Redis/Celery → Worker → MySQL（真实依赖） | 测试环境 Compose 或 CI 服务容器 |
| Docker | 真实容器的判题与沙箱样例集（15.2） | 带 docker 标记的 Pytest |
| E2E | 登录 → 提交 → 终态 → 排行榜 | 接口自动化脚本；演示时再做一次前端手动验证 |
| Failure | Worker 中断、Redis 短断、重复投递、容器超时、榜单漂移 | 故障演练（15.2），记录到 docs/evidence/ |
| Load | 提交入队、题目查询、排行榜查询、端到端判题 | Locust 或同类工具（15.3） |

新增 v1.2 验收：禁用/降权下一次鉴权即生效；隐藏输入经 stderr 回显仍不外泄；在途编辑与并发提交约束成立；历史提交限制快照不变；追踪 ID 与幂等键独立。管理员创建命令不保存或输出明文密码。

必须覆盖的几个“会出事”的测试：　① 同一用户并发 AC 同一题，只计一次分；② 用一个非管理员账号请求全部接口，响应与缓存里没有隐藏用例；③ 两个 Worker 同时 claim 同一提交，只有一个成功；④ 旧 Worker 的 finalize 被 attempts 围栏拒绝；⑤ 补偿扫描不会对已终态的提交重新入队。

### 15.2 判题样例集与故障演练

#### 沙箱与判题样例集

样例集同时是“沙箱验收”和“判题回归”：每次修改执行器、镜像或参数后都要全部通过。

| 样例 | 用户代码的行为 | 期望结果 |
| --- | --- | --- |
| 正确解答 | 输出与期望一致 | ACCEPTED |
| ASCII 行尾空白 / 末尾空行 | 每行多余 ASCII 空格/制表符/回车、CRLF 与末尾空行 | ACCEPTED（按 7.3.1 规整） |
| Unicode 与非法编码边界 | NBSP、组合字符、非法 UTF-8 不得被扩大归一化 | 按 7.3.1 区分，预期 WRONG_ANSWER |
| 错误答案 | 输出内容不同 | WRONG_ANSWER |
| 编译错误（C++） | 语法错误 | COMPILE_ERROR，输出被截断 |
| 运行时错误 | 除零、数组越界、未捕获异常 | RUNTIME_ERROR |
| 死循环 | 无限循环 | TIME_LIMIT，容器被回收 |
| 内存炸弹 | 不断申请内存 | MEMORY_LIMIT |
| 输出洪泛 | 无限打印 | OUTPUT_LIMIT |
| fork 炸弹 | 不断创建进程 | 宿主机不受影响；容器被 pids 限制与回收终止，不留下孤儿容器 |
| 访问网络 | 尝试连接外部地址 | 失败（network none） |
| 写根文件系统 | 尝试写 /etc、/usr | 失败（只读根） |
| 寻找期望输出 | 遍历文件系统找 expected / 测试数据 | 找不到（期望输出不在容器内） |
| 探测 docker.sock | 检查 /var/run/docker.sock | 不存在 |
| 读取其他提交目录 | 尝试访问别的提交的工作目录 | 不可见 |

#### 故障演练清单

| 演练 | 操作 | 期望表现 |
| --- | --- | --- |
| Worker 崩溃 | 判题进行中 kill -9 Worker | lease 过期后被接管并重判，最终终态；无孤儿容器遗留超过阈值 |
| 重复消息 | 手工对同一 submission_id 入队两次 | 只判一次；第二个 Worker 记录 task.claim_lost |
| 入队失败 | 提交时临时停止 Redis，随后恢复 | 用户得到 202；恢复后 stale 扫描补偿入队 |
| Redis 重启并清空 | FLUSHALL 后观察 | 排队中的提交被补偿；榜单可重建；缓存回源 |
| 榜单漂移 | 手工删除 ZSET | 触发重建后与 MySQL 一致 |
| MySQL 短断 | 停止 MySQL 10–30 s 再启动 | API 503 后恢复；Worker 重试 |
| Docker 不可用 | 停止 Docker 守护进程后提交 | InfraError 退避重试，用尽后 FAILED（INFRA_ERROR） |
| 过期 Worker 回写 | 用测试桩模拟旧 attempts 回写 | 围栏拒绝，记录 finalize.fenced |

每次演练把“操作、现象、日志片段、结论”写入 docs/evidence/failure-drills.md，这是面试时最有说服力的材料。

### 15.3 压测方案

先区分口径：　“提交接口延迟”只包含入队（落库 + 入队 + 返回 202）；“端到端时延”包含排队时间 + 判题时间。二者混在一起报告，数字就没有意义。

#### 场景

| 场景 | 目的 | 控制变量 |
| --- | --- | --- |
| S1 题目详情读取 | 观察缓存收益（缓存关 / 开对比） | 固定并发与热点分布 |
| S2 提交入队接口 | 测量入队延迟与成功率 | 暂停 Worker，隔离判题耗时 |
| S3 端到端判题 | 按固定速率提交，观察队列堆积、排队时间、端到端时延与吞吐 | Worker 并发度固定为 2 |
| S4 排行榜读取 | Top N 与个人名次的延迟 | 榜单规模固定 |
| S5 提交历史分页 | 游标分页 vs OFFSET 深翻页 | 10⁶ 级数据量 |

#### 指标与口径

| 指标 | 口径 |
| --- | --- |
| 入队延迟 P50 / P95 / P99 | S2：POST /submissions 的响应时间（仅含落库与入队） |
| 排队时间 | started_at − queued_at |
| 判题耗时 | finished_at − started_at |
| 端到端时延 | finished_at − created_at |
| 吞吐 | 每分钟完成的判题数（Worker 并发度固定时的上限） |
| 错误率 | 非 2xx 比例；FAILED 提交占比 |
| 队列堆积 | judge 队列长度峰值与恢复时间 |
| MySQL | 慢查询、Rows_examined、索引命中（EXPLAIN） |
| Redis | 命中率、内存占用、Key 数量 |

#### 报告模板与规则

- 每份报告包含：环境（机型、版本、Worker 并发度）→ 数据量 → 场景与参数 → 结果表 → 瓶颈分析 → 优化动作 → 复测结果。

- 至少做三组“优化前 / 优化后”对比：索引（EXPLAIN）、缓存开关、游标 vs OFFSET；限流算法对比（固定窗口 vs 滑动窗口）作为可选实验。

- 压测在 12 月完成（1 月为期末）；报告放在 docs/loadtest/，脚本放在 scripts/loadtest/。

简历证据规则：　只有真实压测得到的数据才能写入简历，例如“TP95 从 X ms 降至 Y ms”；没有测试就不要填写具体性能数字。

### 15.4 持续集成（GitHub Actions）

| Job | 内容 | 触发 |
| --- | --- | --- |
| lint-unit | ruff 检查与格式；pytest -m "not docker" 单元与 API 测试；前端 vue-tsc 与 lint | 每次 push / PR |
| integration | 以服务容器启动 MySQL 与 Redis，执行迁移后运行集成测试 | 每次 push / PR |
| docker-judge | 构建判题镜像，运行 pytest -m docker（沙箱样例集） | 合并到主分支、每日或手动 |
| build | 构建 api / worker / 前端镜像，确认能成功构建 | 合并到主分支 |

规划02 对 Pytest / CI 的要求是“关键 Service / 接口测试、Mock、GitHub Actions 自动测试与 Docker 构建”，上表即对应落地。

## 16. 项目目录结构

v1.2：沿用原分层骨架，补充协作目录、Mermaid 图源与私有原件位置。下面是目标结构，不代表这些文件已经实现。

```text
oj-platform/
├─ AGENTS.md
├─ .gitignore                   # 含 ~$*、*.docx、local-reference/、真实 .env 与凭据
├─ .gitattributes
├─ Makefile
├─ README.md
├─ .pre-commit-config.yaml
├─ git-push-workflow/SKILL.md    # 新版 Git 规则，原样复制
├─ local-reference/             # 私有 Word 原件与校验记录，不入库
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/                   # v1/、deps.py
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/               # 对外 / 管理端分离
│  │  ├─ services/
│  │  ├─ repositories/
│  │  ├─ tasks/
│  │  └─ judge/
│  ├─ tests/                    # unit/ api/ integration/ failure/ docker/ fixtures/
│  ├─ alembic/
│  ├─ pyproject.toml
│  ├─ uv.lock
│  ├─ .python-version
│  └─ Dockerfile.dev            # 06末尾环境探针使用；06不做API容器化
├─ frontend/src/
├─ deploy/
│  ├─ docker-compose.yml       # 后续目标部署
│  ├─ docker-compose.dev.yml   # 06只起MySQL和Redis，API本地运行
│  ├─ nginx.conf
│  ├─ mysql/my.cnf
│  └─ .env.example             # 唯一环境模板；真实 deploy/.env 忽略
├─ judge-images/
│  ├─ python/
│  └─ cpp/                     # 可砍的第二语言
├─ scripts/
│  ├─ create_admin.py          # M1一次性管理员命令；06不实现
│  ├─ seed_data.py
│  ├─ loadtest/
│  ├─ backup.sh
│  └─ rebuild_ranking.py
├─ docs/
│  ├─ project-design.md        # 当前设计主本
│  ├─ development-workflow.md  # 通用准备模板及OJ约束
│  ├─ ai-workflow.md
│  ├─ revisions/v1.2.md
│  ├─ adr/                    # 沿用001—012，新决策从013开始
│  ├─ figures/                # 每张图一份Mermaid Markdown图源
│  │  └─ reference/            # v1.1 PNG仅作存档
│  ├─ learning/
│  ├─ modules/
│  ├─ evidence/
│  ├─ loadtest/
│  └─ interview-qa.md
└─ .github/workflows/ci.yml
```

工程约束：judge/ 不依赖 Celery、不读写业务表；tasks/ 只做薄封装。目录和规则文件、uv锁定、Ruff/pytest、/healthz与测试、数据库/Redis Compose、最小CI和README属于阶段06主线。

阶段06末尾再安排 Dockerfile.dev 和 Worker 环境探针，限时半天；探针不通过不阻塞认证切片，必须记录结果和原因。阶段06 API 本地运行，不做API容器化。

本轮仅交付设计与协作文档；工程目录、业务代码、迁移、CI配置的实际创建在用户确认进入阶段06后分节完成。

## 17. 开发里程碑与验收标准

v1.2：按2026-10-19实际起点重排；M1顺延，M2及12月压测窗口保持。日期是目标，不代表验收已经通过。严格级理解与正确性门槛不能被时间表覆盖。

### 17.1 里程碑

| 阶段 | 日期 | 目标 | 验收标准 |
| --- | --- | --- | --- |
| M1 需求与骨架 | 2026-10-19—11-08 | v1.2、工程初始化、数据库/迁移、认证/RBAC、题库与测试数据管理、初始管理员命令 | 严格级检查通过；核心API及迁移可验证；最小CI运行后通过 |
| M2 判题闭环 | 2026-11-01—11-30 | Python执行器、Celery、状态机、恢复、重试、沙箱及云上冒烟 | 稳定终态、样例集、Worker故障恢复和云上流程验收 |
| M3 工程化与简历v1 | 2026-12-01—12-15 | 榜单/缓存/限流/日志/健康检查、正式部署、三组前端页面、简历v1 | 真实运行及测试；管理员先用Swagger |
| M4 性能与稳定性 | 2026-12-16—12-31 | 造数、EXPLAIN、压测S1—S5、故障与备份恢复演练、证据整理 | 真实报告及可复现记录，12月窗口不挪用 |
| 期末与Freeze | 2027-01-01—01-10 | Bug修复、文档与面试证据；01-10冻结 | 不再增加功能 |

进度吃紧时优先砍比赛、讨论、C++等增强范围，不删除核心判题、可靠性、测试和部署验收；不得跳过严格级模块的理解与正确性检查。冻结日期为2027-01-10。

### 17.2 重排执行表

| 日期 | 安排 | 验收重点 |
| --- | --- | --- |
| 10/19—10/20 | v1.2设计修订与独立提交 | 修订清单、图文/规则diff与校验记录 |
| 10/21—10/23 | 阶段06主线 | 目录规则、uv锁定、Ruff/pytest、healthz、数据库/Redis、最小CI与README |
| 阶段06末尾，限半天 | Dockerfile.dev与Worker环境探针 | 四步文件/权限验收；失败记录ADR-016和learning，认证切片可继续 |
| 10/24—10/29 | 数据库、迁移、认证垂直切片 | 用户完成严格级核心，注册/登录/写库/测试贯通 |
| 10/30—11/08 | M1收尾优先；仅允许独立的M2前置 | RBAC、题库、测试数据管理及管理员命令；前置仅比对器、判题镜像、DockerRunner本地脚本 |
| 11/09—11/11 | W5专项复核（三天） | 逐条推演，用户复述并确认后再实现 |
| 11/12—11/15 | Python主链路 | 提交→领取→执行→终态 |
| 11/16—11/22 | lease、恢复、补偿、重试、沙箱专项 | 故障收敛、围栏及资源回收 |
| 11/23—11/30 | 云上冒烟与补齐M2 | M2验收 |
| 12/01—12/15 | M3与前端三组页面、简历v1 | 登录；题库/题目详情含Monaco；结果/历史；管理员用Swagger |
| 12/16—12/31 | M4，窗口保持 | 压测、EXPLAIN、故障、备份恢复及证据 |
| 2027/01/01—01/10 | 修复与冻结 | 无新功能，01/10冻结 |

交叠规则：10/30—11/08一律M1优先；M2前置只做不依赖M1的比对器、判题镜像和DockerRunner本地脚本，不抢跑待专项复核的设计变更。截至11/08若M1未验收，暂停M2前置并报告进度风险。

### 17.3 本次不修改的专项设计

2026-11-09—11-11复核：幂等重放顺序；lease/续租/接管/围栏；重试门槛与恢复上界；沙箱挂载及目录隔离；榜单重建与并发。先按现有设计推演，由用户复述后定稿。本次只同步追踪/幂等字段命名及已确认需求，不调整这些流程语义。

Mermaid重绘限时半天，只修已确认的不一致；未完成不阻塞阶段06，完成状态如实记录。

截至12/15只保证13.1的三组页面；榜单页与管理端页面后置，管理员先通过Swagger。其他前端页面不挤占12月压测与故障演练窗口。

## 18. 面试证据链

v1.1 变更｜证据指定到具体文件路径；新增“高频追问清单”（映射到本文章节）与“模块复盘五问”的落地位置（I-24）。

项目完成后，不能只保留“功能能跑”，而要形成可以继续追问 2–3 层的证据链。每一条证据都要对应一个具体文件，写在 docs/evidence/ 下。

| 面试主题 | 必须能回答 | 对应证据（文件） |
| --- | --- | --- |
| 异步判题 | 为什么需要队列？如何削峰？失败怎么重试？怎么幂等？ | docs/evidence/async-judge.md：架构图 + 状态机图 + 重试日志 |
| 可靠性 | Worker 挂掉会怎样？重复消息怎么办？旧 Worker 复活怎么办？ | docs/evidence/failure-drills.md：演练记录 + 日志片段 |
| 沙箱 | 如何限制 CPU/内存/时间/进程？超时怎么回收？为什么每点一个容器？ | docs/evidence/sandbox.md：参数表 + 样例集结果 |
| 排行榜与一致性 | 为什么用 ZSET？怎么避免重复计分？乱序写怎么办？Redis 丢了怎么办？ | docs/evidence/ranking.md：score 编码 + GT 说明 + 重建演练 |
| Redis | 缓存怎么失效？穿透/击穿/雪崩怎么处理？限流怎么做？ | docs/evidence/redis.md：Key 设计 + 示例数据 + 压测对比 |
| MySQL | 索引为什么这样设计？EXPLAIN 怎么看？游标分页为什么更好？ | docs/evidence/mysql-explain.md：前后 SQL + EXPLAIN + 实测耗时 |
| 安全 | 隐藏用例怎么保护？docker.sock 的风险怎么说明？ | docs/evidence/security.md：威胁表 + 残余风险声明 |
| 工程化 | 怎么测试？怎么部署？怎么排查问题？ | .github/workflows/ci.yml、README、日志检索示例 |
| 性能 | QPS/TP95 从哪里来？为什么优化有效？入队延迟与端到端时延的区别？ | docs/loadtest/*.md：Locust 报告 + 优化前后数据 |

项目讲解主线：　建议最终能够连续讲 20–30 分钟：业务背景 → 架构 → 核心链路 → 关键难点 → 取舍 → 优化 → 压测 → 故障恢复 → 安全边界 → 下一步。

### 18.1 高频追问清单

| 追问 | 回答的抓手（本文章节） |
| --- | --- |
| 为什么判题要异步？HTTP 里直接跑行不行？ | 5.1；4.1 |
| 先入队还是先落库？两者之间失败了怎么办？ | 5.1 步骤 3–4；8.3；ADR-009 |
| Worker 崩溃后提交会卡在 RUNNING 吗？怎么发现、怎么恢复？ | 8.3；8.5 场景 2 |
| Celery 默认配置有什么坑？为什么要延迟确认、预取设为 1？ | 8.4 |
| visibility_timeout 设小了会怎样？ | 8.4（重复投递给另一个 Worker） |
| 怎么保证同一提交不会被判两次、旧结果不会覆盖新结果？ | 8.1；8.5 场景 1、3 |
| 排行榜怎么避免重复计分？为什么用 ZADD … GT 而不是 ZINCRBY？ | 10.4；8.1 |
| 用户的代码能读到标准答案吗？为什么每个测试点一个容器？ | 7.1；7.2；ADR-011 |
| 挂载 docker.sock 有什么风险？你怎么处理？ | 4.3；7.6；ADR-008 |
| 缓存穿透、击穿、雪崩分别怎么处理？缓存与数据库怎么保持一致？ | 10.2 |
| Redis 同时做队列和缓存，会出什么问题？ | 10.5；ADR-012 |
| 提交历史为什么用游标分页？联合索引顺序怎么定？ | 9.3；9.4 |
| 压测数字怎么来的？入队延迟和端到端时延有什么区别？ | 15.3 |
| 如果数据量扩大 10 倍，你会先改什么？ | 19.2（归档/分区、拆 Redis、对象存储） |

### 18.2 模块复盘五问

规划02 要求每完成一个模块，固定回答五个问题，并沉淀为项目面试题库。落地方式：每个模块完成后，在 docs/interview-qa.md 追加一节，包含：

- 为什么这么设计？

- 有没有替代方案？为什么没选？

- 瓶颈在哪里？

- 数据量扩大 10 倍时怎么办？

- 面试官最可能追问什么？

## 19. 非目标与停止线

v1.1 变更｜新增 19.2 后置优化清单（每项写明触发条件）与 19.3 技术准入三问（I-26、D-04）。

### 19.1 非目标

- 不为了技术名词扩张而同时引入多个消息队列、多个任务框架或多个 Agent 式组件。

- 不把比赛、评论、多语言等增强功能放在核心判题链路之前。

- 不为了“看起来高并发”而虚构性能数字。

- 不把未真正理解的代码直接写进简历；使用 Codex/Claude Code/Trae 提速后，仍必须逐行读懂并能重写。

- 当项目达到“能投”标准后，停止无止境加功能，转向算法、八股、模拟面试和真实投递。

### 19.2 后置优化清单

下面这些“可选”项统一在这里登记，只有触发条件出现时才做；它们都不在 MVP 内。

| 项 | 触发条件 | 说明 |
| --- | --- | --- |
| SSE 推送结果 | 压测显示轮询的读压力成为瓶颈，或需要更好的实时体验 | 与轮询接口并存，渐进替换 |
| Redis Hash 缓存实时状态 | 查询提交状态的 MySQL 读成为瓶颈 | Redis 仅作缓存，终态仍以 MySQL 为准 |
| Outbox 表 | 补偿入队的延迟（秒到分钟级）不可接受 | 同一事务写 outbox，由发布器可靠投递；见 ADR-009 |
| 拆分 Redis 为两个实例 | 压测发现缓存与队列相互影响 | 队列实例 noeviction，缓存实例可淘汰 |
| submissions 归档 / 分区 | 表行数增长到影响索引与备份 | 按时间归档历史终态提交 |
| 重判（rejudge） | 题目测试数据修改后需要刷新历史结果 | 需要同时回滚 user_problem_stats 与榜单，设计成本高 |
| 比赛 / 题解 / 评论 | 核心版本冻结且仍有时间 | P1 增强项 |
| 更多判题语言 | C++ 稳定后 | 每增加一种语言需要镜像、编译/运行配置与样例集 |
| 特殊判题 / 浮点容差 | 出现需要它的题目 | 引入比对器扩展点 |
| refresh token + httpOnly Cookie | 需要更完整的登出与吊销，或要降低 XSS 窃取 token 的风险 | 需要同时加 CSRF 防护 |
| gVisor / rootless Docker / docker-socket-proxy | 准备长期公开运行，或需要更强的隔离 | 见 7.6 |
| 对象存储存放大测试数据 | 单点数据超过 1 MB 的需求出现 | MySQL 只存元信息与哈希 |
| 滑动窗口 / 令牌桶限流 | M4 对比实验，或固定窗口的边界突发成为问题 | 可作为压测的对比实验 |

### 19.3 技术准入三问

规划02 的最终执行原则：任何新增技术都先问下面三个问题；三个答案中有两个是否定，就先不学、不加。

| # | 问题 | 判断 |
| --- | --- | --- |
| 1 | 目标 JD 是否需要它？ | 是 / 否 |
| 2 | 能否在项目里产生真实价值（解决一个真实存在的问题）？ | 是 / 否 |
| 3 | 能否在面试中讲清楚（原理、取舍、替代方案）？ | 是 / 否 |

最终停止线：2027-01-10 冻结核心版本；2026 年 12 月完成压测与故障演练。进度不足只砍范围，不跳过严格级模块的理解和正确性检查；冻结后仅修 Bug、补文档与整理面试证据。

## 20. 附录：关键决策记录

v1.1 变更｜新增 ADR-007 ～ ADR-012，并在 docs/adr/ 中同步维护（I-04、I-05、I-13、I-17）。

| 编号 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- |
| ADR-001 | 选择 OJ 作为主项目 | 天然覆盖异步任务、队列、容器运行、缓存、排行榜、限流、压测等后端面试点。 | 已采纳 |
| ADR-002 | 采用 Celery + Redis | 满足异步判题、任务状态、重试和削峰要求，避免重复建设任务框架；可靠性以 MySQL 状态机为准，不依赖 broker 重投。 | 已采纳 |
| ADR-003 | Docker 作为判题隔离层 | 实现基础资源限制与执行环境隔离；明确不把项目定位为专业安全产品。 | 已采纳 |
| ADR-004 | Redis ZSET 做排行榜 | 适合实时排名和 Top N 查询；MySQL 作为可恢复事实数据来源。 | 已采纳 |
| ADR-005 | MVP 只支持 1–2 种语言 | 优先稳定判题链路，再扩展多语言；Python 先行，C++ 作为第二种。 | 已采纳 |
| ADR-006 | 真实数据优先 | 压测、失败案例、索引优化和性能数字必须来自真实运行结果。 | 已采纳 |
| ADR-007 | API 层 async，Worker 同步 | API 以 I/O 为主，适合 async；Worker 是 prefork 同步进程，天然适配 Docker SDK；CPU 密集操作放线程池。 | 已采纳 |
| ADR-008 | Worker 挂载 docker.sock，用户容器不挂载 | Worker 必须能启动容器；以“Worker 可信、用户代码不可信”划分信任边界，缓解措施见 4.3；docker-socket-proxy 与 rootless 作为备选。 | 已采纳（有已知风险） |
| ADR-009 | 先落库后入队 + 补偿扫描；Outbox 后置 | 事务提交后入队，失败由扫描兜底；MVP 接受“秒到分钟级”的补偿延迟，以换取更简单的实现。 | 已采纳 |
| ADR-010 | 计分粒度为（用户，题目），以 user_problem_stats 为准 | 排行榜含义是“通过了多少道不同的题”；首次 AC 由条件更新判定；榜单可重建，写入用 ZADD … GT。 | 已采纳 |
| ADR-011 | 每个测试点一个一次性容器 | 隔离最干净、实现最直观、期望输出不进容器；启动开销以 M4 实测评估，必要时再考虑“每提交一个容器”。 | 已采纳（待实测） |
| ADR-012 | Redis 单实例 noeviction，db0 broker / db1 其余 | 队列键不能被淘汰；缓存键必带 TTL 且总量可控；实测互相影响再拆实例。 | 已采纳 |
| ADR-013 | MVP鉴权按主键查库，不缓存角色/状态 | 保证禁用、降权立即生效；未来缓存需压测和新ADR | 已采纳 |
| ADR-014 | 隐藏点不回传用户stdout/stderr | 用户可把输入写进stderr，截断不能阻止泄露 | 已采纳 |
| ADR-015 | 在途禁止修改测试点/限制，提交保留限制快照 | 保持一次提交使用的条件稳定；具体事务由M1严格级设计确认 | 需求已采纳，事务方案待确认 |
| ADR-016 | WSL2 Linux文件系统开发，原生Engine优先评估 | 以真实文件/权限链路验收；06末尾探针半天且不阻塞认证 | 环境选择已采纳，Engine/探针待验收 |

## 附录 A：MVP 开发验收清单

- [ ] 一次性管理员命令可用，密码不进入迁移、源码、参数或日志
- [ ] 在途编辑与提交并发约束验收；限制快照保持稳定
- [ ] request_id与idempotency_key职责分离；隐藏点stdout/stderr响应为白名单
- [ ] Worker/并发测试使用独立测试库并清表

#### 认证与题库

- [ ] JWT 登录、注册、RBAC 可用；角色与状态不缓存，禁用/降权立即生效

- [ ] 题库分页、题目详情、管理员 CRUD 与发布/下线可用

- [ ] 测试数据区分样例与隐藏；对外 DTO 不含隐藏用例

#### 提交与判题

- [ ] 提交接口强制 Idempotency-Key，重复提交返回同一 submission_id

- [ ] 落库事务提交后才入队；入队失败可被补偿

- [ ] Redis/Celery 队列可用，judge 与 maintenance 分队列

- [ ] Celery Worker 能启动 Docker 判题容器；期望输出不进入容器

- [ ] 编译错误/运行时错误/答案错误/超时/内存超限/输出超限可区分

- [ ] 判题结果回写 MySQL；提交历史（游标分页）可查询

#### 可靠性

- [ ] claim / finalize 为条件更新；旧 Worker 的回写被 attempts 围栏拒绝

- [ ] kill Worker 后 lease 过期被接管，提交收敛到终态

- [ ] Worker 失败可有限次重试，次数用尽进入 FAILED

- [ ] Docker 容器与临时目录可回收；孤儿回收任务有效

#### 缓存、榜单与限流

- [ ] Redis ZSET 排行榜可用；首次 AC 才计分；可整体重建

- [ ] 题目缓存含穿透、击穿、雪崩处理；写题目后缓存失效

- [ ] 提交限流与在途上限生效；429 带 Retry-After

#### 沙箱

- [ ] 沙箱样例集（15.2）全部通过

- [ ] 无网络、只读根、丢弃 capability、资源限制均已验证

#### 工程与交付

- [ ] Swagger/OpenAPI 可访问

- [ ] Pytest 核心测试通过；CI 绿

- [ ] Docker Compose 可一键部署；Nginx 反向代理可用；迁移独立步骤

- [ ] 日志含 request_id / submission_id；/healthz 与 /readyz 可用

- [ ] 有真实压测记录与 EXPLAIN 前后对比

- [ ] 故障演练记录齐全；备份与恢复演练完成

- [ ] README 写清部署与设计取舍；docs/evidence 与 interview-qa 完整

- [ ] 能围绕项目连续讲解 20–30 分钟

## 附录 B：需求追踪矩阵

每条功能需求都能追踪到接口、数据表和测试；找不到对应项的需求，说明设计有缺口。

| 需求 | 接口（节） | 主要数据表 | 验证 |
| --- | --- | --- | --- |
| FR-01 认证与授权 | 11.2；11.6 /admin/users | users | API 测试：登录、越权、禁用账号 |
| FR-02 题库管理 | 11.3；11.6 题目/测试点/标签 | problems、test_cases、tags、problem_tags | API 测试：发布校验、DTO 脱敏 |
| FR-03 代码提交 | 11.4 POST /submissions | submissions、user_problem_stats | API 测试：幂等、校验顺序 |
| FR-04 异步判题 | —（内部） | submissions、submission_cases | 集成测试 + 沙箱样例集 |
| FR-05 结果持久化 | 11.4 GET /submissions/{id} | submissions、submission_cases | 集成测试：字段与时间点 |
| FR-06 提交历史 | 11.4 GET /submissions | submissions | API 测试：游标分页；EXPLAIN |
| FR-07 排行榜 | 11.4 /rankings、/rankings/me；11.6 rebuild | user_problem_stats | 并发 AC 测试；重建演练 |
| FR-08 限流与超时 | 全部接口（10.3） | submissions（在途计数） | 限流脚本单元测试；压测 |
| FR-09 重试、幂等与恢复 | —（内部） | submissions（attempts、lease） | 故障演练 8 项 |
| FR-10 管理端 | 11.6 | audit_logs 及全部管理表 | API 测试：权限、审计 |
| FR-11 测试数据保护 | 11.3、11.4、11.5 | test_cases | 非管理员全接口断言；缓存检查 |
| FR-12 运维可见 | 11.6 stats/queue；11.7 | submissions | 健康检查与日志链路检查 |

## 附录 C：版本变更摘要

### C.1 v1.0 → v1.1 变更摘要

以下历史摘要保留原编号；v1.2修订见C.2。

编号对应《OJ 设计文档改进点分析》；“章节”指本文档中的位置。

| 编号 | 变更 | 章节 |
| --- | --- | --- |
| I-01 | 排行榜按（用户，题目）首次 AC 计分；新增 user_problem_stats；score 编码；ZADD … GT | 8.1、9.2、10.4 |
| I-02 | 新增 attempts、lease、围栏；状态机增加回退与恢复边 | 5.3、8.2、8.3、9.2 |
| I-03 | 先提交事务再入队；补偿扫描；Outbox 后置 | 5.1、8.3、ADR-009 |
| I-04 | Celery 可靠性配置基线（延迟确认、预取、visibility_timeout、分队列） | 8.4 |
| I-05 | Worker 与 Docker 的信任边界；docker.sock 风险；同路径挂载 | 4.3、7.1、14.1、ADR-008 |
| I-06 | 每测试点一个容器；Docker 参数基线；编译限制；OOM/超时判定；孤儿回收 | 7.2、7.4、7.5 |
| I-07 | 比对器规则；Verdict 优先级；遇首个非 AC 即停；新增 OUTPUT_LIMIT | 5.3、7.3 |
| I-08 | 样例/隐藏用例区分；对外 DTO；结果脱敏；缓存与日志边界 | 9.2、10.2、11.5、12.3 |
| I-09 | 接口补全到 30 个并分组；统一错误体、分页与状态码；Idempotency-Key 必填 | 11 |
| I-10 | 补 tags、problem_tags、stats；字段与类型统一；DDL；唯一幂等键 | 9 |
| I-11 | 缓存穿透/击穿/雪崩与一致性边界 | 10.2 |
| I-12 | 限流算法、维度、阈值形态与在途上限；降级策略 | 10.3 |
| I-13 | Redis 淘汰策略与隔离；数据丢失恢复表 | 10.1、10.5、ADR-012 |
| I-14 | 索引与查询对应；游标分页；造数与 EXPLAIN 方案 | 9.3、9.4 |
| I-15 | 大字段上限与截断规则 | 9.5 |
| I-16 | 认证与会话细则；前端安全（XSS、CSP、token） | 12.2、13.3 |
| I-17 | API async 与 Worker 同步的选型 | 4.4、ADR-007 |
| I-18 | 日志规范、request_id、健康检查、队列与耗时指标 | 14.4 |
| I-19 | 压测场景、指标口径、报告模板；压测放在 12 月 | 15.3 |
| I-20 | 里程碑落到日期；云上冒烟前移；砍刀顺序；冻结日 | 17 |
| I-21 | 上线检查清单、内存预算、备份与恢复演练 | 14.2–14.6 |
| I-22 | GitHub Actions CI | 15.4、16 |
| I-23 | 只读账户与分析视图；造数复用；字段 COMMENT | 9.7 |
| I-24 | 证据指定到文件；高频追问清单；复盘五问落地 | 16、18 |
| I-25 | 沙箱残余风险声明与可选加固 | 7.6 |
| I-26 | 后置优化清单（含触发条件） | 19.2 |
| D-01 | 重绘总体架构图；新增时序图、状态机图、ER 图 | 4.1、5.1、5.3、9.1 |
| D-02 | 目录与编号统一；模块改为独立小节；新增附录 B、C | 全文 |
| D-03 | A4、微软雅黑、表格宽度统一、页码 | 全文 |
| D-04 | 技术准入三问；需求追踪矩阵 | 19.3、附录 B |

说明：　涉及 Docker、Celery、Redis、阿里云的参数与规则，均基于通用实践写成“初始建议”，代码片段为示意而非最终实现；上线前请以官方文档和你自己的实测为准。

### C.2 v1.1 → v1.2 变更摘要

修订日期：2026-10-19。R01—R13已由用户批准，细节与差异记录见 [revisions/v1.2.md](revisions/v1.2.md)。

| 编号 | 本次决定 | 主要章节 |
| --- | --- | --- |
| R01 | 当前版本v1.2，Markdown维护主本，保留历史变更 | 封面、附录C |
| R02 | OJ范围依P0/P1；OpenAPI不一致先停下确认 | 1、2、11、19 |
| R03 | 冻结2027-01-10、严格级不跳过；M1顺延，W5复核11/09—11/11，主链路11/12—11/15；前端三组页面 | 2.4、13、17、19 |
| R04 | 鉴权按主键查库，MVP不缓存角色/状态 | 6.1、12.2、15、附录A |
| R05 | 隐藏点不回传stdout/stderr；样例和编译输出可截断回传 | 11.5、12.3、15 |
| R06 | 在途禁止改测试点/限制；保存限制快照；事务方案由用户在M1确认 | 5、6.2、9、11.6、15 |
| R07 | 一次性命令创建管理员，密码不进迁移/源码 | 6.1、11.2、12、14、16 |
| R08 | request_id只追踪；独立idempotency_key与唯一约束 | 5、8.1（仅名称）、9、11、14 |
| R09 | 纯API可回滚；Worker/并发用独立库并清表 | 15 |
| R10 | BIGINT自增，ID远小于2^53，接口继续数字 | 2.4、9.1、11.1 |
| R11 | 四张原图存档、Mermaid单一来源；限半天，只修已确认图文差异 | 4、5、9、16 |
| R12 | 明确ASCII空白、CRLF和Unicode/非法编码比较规则 | 7.3.1、15.2 |
| R13 | 补协作目录和ADR-013起的新记录；WSL2开发，06只起数据库/Redis、API本地运行 | 4.3、14、16、20 |

五类专项设计保留至W5复核，不因本次版本升级提前变更。阶段06须在本次独立文档提交汇报、用户确认后启动。
