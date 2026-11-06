# 题目草稿与标签（07.8）

## 1 职责
题目草稿与标签管理由 07.8 落地，07.9 接入在途编辑保护。
管理员创建、查询和修改题目，显式创建标签；题目、关联与审计共同提交。07.9 扩展为 DRAFT/OFFLINE 可写。
公开题库、发布/下线留给 07.10；测试点与在途保护的离线实现见 [测试点模块](test_case.md)，真实依赖验证待做。

## 2 主要文件
| 文件 | 作用 |
| --- | --- |
| backend/app/models/problem.py | problems、tags、problem_tags 的既有表映射 |
| backend/app/repositories/problem.py | 查询、锁定读、关联替换与 flush |
| backend/app/schemas/problem.py | 管理输入、列表/详情与 UTC 响应白名单 |
| backend/app/services/problem.py | 建题/修改事务、精确约束分类、安全审计 |
| backend/app/api/v1/admin_problem.py | 六接口和 router 级实际字节限额 |
| backend/app/api/deps.py、api/v1/admin.py | 请求级注入与统一管理员鉴权 |

## 3 调用链
1. main 已挂的管理员父 router 进入本子路由；写请求由 route class 累计实际 body 字节。
2. 共用 require_admin 查询本次角色/状态；服务与仓储共享请求级会话。
3. 建题校验已有标签、插入 DRAFT、替换关联、写审计；PUT 先锁题目并判定 DRAFT/OFFLINE，限制实际变化再查在途。
4. 仓储只 flush/refresh，服务事务成功退出才返回白名单 DTO；失败共同回滚。
5. 列表显式不选完整题面，并批量查询标签；只读请求不写审计。

## 4 核心原理与关键决策
- 契约见 [设计 §11.6](../project-design.md#116-管理接口apiv1admin)，字段见设计 §9.2。
- slug 是 1–64 位小写字母/数字与分段连字符，创建后固定；PUT 六字段全部必填。
- DRAFT/OFFLINE 可修改两个正整数限制（上限 4294967295）；PUBLISHED 409，需先下线。
- 本节无发布/下线入口；OFFLINE 测试只能人工造数、非端到端；保护仅离线验证，不声称实库验收。
- 唯一性靠既有数据库约束；预查标签不消除并发删除，1452 仍须精确分类并整笔回滚。
- 摘要只取枚举、ID/slug、长度和数量，先生成再限 2048 字符；IP 复用规范化。
- route class 每请求独立计数，超过 256*1024 字节触发专用 HTTPException。
  FastAPI 在 body 解析层将 HTTPException 原样抛出，普通异常则转换为 400
  （fastapi/routing.py 的 except HTTPException: raise / except Exception 分支）。
  保留专用 HTTPException 子类，使超限信号保持 413；包装器捕获后统一渲染为 error_response，
  返回 PAYLOAD_TOO_LARGE 和 request_id；不改全局中间件。
  若普通异常绕过解析层才会变成 500，本实现不依赖该路径。
- 不缓存题目，缓存失效 N/A；管理详情不携带样例或隐藏测试数据。

## 5 异常与边界
- 身份无效 401、普通/禁用用户 403、题目不存在 404、PUBLISHED、在途限制变化或已知唯一键冲突 409。
- 非法字段、重复 tag_ids 或标签不存在为 422；未知字段名和原输入不回显。
- 1062 仅识别 uk_problems_slug / uk_tags_name；1452 仅将 fk_problem_tags_tag 映射为标签不存在。
- 未知约束/格式返回安全 500，依赖操作故障/池超时 503；不输出 SQL、参数或异常原文。
- 413 只覆盖本节 JSON 写入口；按真实消息分块计数，Content-Length 不能放行超限体。
- 测试为离线事务替身与 SQL 声明验证；真实 MySQL 并发、持久化回滚、排序规则仍待实测。
- 部署层 Nginx 未验证；公开 DTO 与发布门槛由后续小节实现，不以本节测试替代。

## 6 怎么测
在 backend/ 执行 pytest tests/unit/test_problem_service.py tests/api/test_admin_problem.py，
再执行默认 pytest、ruff check .、ruff format --check .（均通过锁定的离线 uv 环境）。
预期测试全绿、无外连；覆盖事务故障、1062/1452、六接口权限/DTO与四项 413 场景。
