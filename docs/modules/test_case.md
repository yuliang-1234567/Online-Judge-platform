# 测试点管理与在途编辑保护（07.9）

## 1 职责
管理员分页读取、创建、全量修改和删除测试点；测试点与审计共同提交。
发布/下线及公开查询留给 07.10；提交接收与 Worker 不在本模块实现。

## 2 主要文件
| 文件 | 作用 |
| --- | --- |
| backend/app/models/test_case.py | 映射既有 test_cases，不改 DDL |
| backend/app/repositories/test_case.py | 归属定位、当前读、分页及 flush |
| backend/app/schemas/test_case.py | 管理 DTO、严格类型与 UTF-8 字节边界 |
| backend/app/services/test_case.py | 摘要、父锁、数量/在途保护、原子审计 |
| backend/app/api/v1/admin_test_case.py | 四接口与 16MiB 子路由 |
| backend/app/repositories/problem.py、services/problem.py | 题目锁、在途当前读与限制变化保护 |
| backend/app/api/deps.py、api/v1/admin.py、core/http.py | 请求级注入、鉴权与安全错误字段 |

## 3 调用链
1. 管理员父 router 统一鉴权；写请求由原接收保护逐块计数，本子路由限额为 16MiB。
2. 创建先锁题目；修改/删除只先无锁定位归属，随后锁父题目并锁定重读目标。
3. DRAFT/OFFLINE 可写，PUBLISHED 返回 409；测试点写操作检查 QUEUED/RUNNING 当前读。
4. 创建在父锁内当前读 ID 集合校验数量；服务计算元数据后由仓储 flush，追加安全审计。
5. 事务成功退出再返回管理 DTO；异常共同回滚。GET 不写审计，删除依赖既有 SET NULL。

## 4 核心原理与关键决策
- 接口、状态、摘要公式和向量见 [设计 §11.6](../project-design.md#116-管理接口apiv1admin)，字节上限见 §9.5。
- 题目锁是协议共同序列化点；在途查询使用 FOR UPDATE，不能使用定位归属时的旧快照。
- RR 且选用既有 idx_sub_problem_status 时，可能锁扫描区间和空结果间隙；不承诺只锁返回行。
  实际锁范围取决于隔离级别/执行计划；不靠间隙锁保证正确，本节不加索引或改服务器配置。
- 两个内容各≤1MiB，允许空串且不裁剪；8 字节长度前缀隔开原始 UTF-8 内容再计算 SHA-256。
  摘要不自动去重；编号由唯一约束裁定，不自动重排。
- 测试点增删改一律检查在途；题目 PUT 只有限制实际变化才检查，限制未变可改题面/标签。
- 业务与审计共事务，摘要只取 ID/编号/样例标记/大小/哈希，最多 2048 字符，IP 统一规范化。
- 16MiB 与原 256KiB 共享同一个 route class，仅覆盖类属性；特殊 HTTPException 保持 413，
  包装器统一 error_response，不改全局中间件或另写接收保护。

## 5 异常与边界
- 401/403/404 沿用统一语义；PUBLISHED、在途及精确编号冲突 409，第 51 点/字段错误 422。
- 只有 1062 + uk_cases_problem_idx 为编号冲突；未知约束安全 500，依赖故障/池超时 503。
- 管理 DTO 可返回完整内容；现有题目 DTO、错误、审计、日志及缓存不含完整测试数据。
- OFFLINE 本节只能替身或后续隔离库人工造数，非端到端；下线入口尚未实现。
- 离线事务/锁替身不证明真实 InnoDB 并发、持久化回滚或 SET NULL；Nginx 未验。
- 未来提交接收须遵守同一题目锁协议；本节不声称已验证该尚未实现的接口。

## 6 怎么测
在 backend/ 运行 pytest tests/unit/test_test_case_service.py tests/api/test_admin_test_case.py，
再运行默认 pytest、ruff check .、ruff format --check .，使用锁定的离线 uv 环境。
覆盖固定哈希向量、状态/字段/权限、50/51 点、原子失败、分块 16MiB 与原 256KiB。
真实服务验证与 07.9 出包另行批准；本模块未运行真实依赖。
