# W5-1b 幂等 key 契约（2026-11-08 补记）

目标：记录用户裁决 C1/S1/D1 的设计落盘、框架证据和未验边界，只定 key 契约。
验收：1. 对应主本仅两行变更；2. 字符、空白、重复头与网络解析边界可判分；3. 比较规则、守卫与学习状态不越权收口。

## 归属与依据

- 用户本轮确认采用 B：将 [712aead](https://github.com/yuliang-1234567/Online-Judge-platform/commit/712aead1e5c515f4112324fc1e9bb8a423576c83) 追认为 W5-1b 主本，本文件补其配套记录。
- 该主本只改 docs/project-design.md 第 1192、965 两行，新增 2 行、删除 2 行；不包含代码、迁移、测试、图源或部署变更。
- 用户已裁决 C1/S1/D1 并批准文字落盘；规则以[设计主文档](../project-design.md)为准，本节不重开其他已批决定。

## 已定契约

- C1：Idempotency-Key 必填，16—64 个 ASCII 字符；仅字母、数字、下划线、连字符，整值匹配 [A-Za-z0-9_-]{16,64}；ASCII 下字符数与字节数相同。
- S1：应用可见空白全部 422，不 trim；非 ASCII 值不接受，不转大小写、不做 Unicode 归一化，大小写保留原样。
- D1：同值/异值重复头均 422，含逗号的单值也 422；实现须读取 request.headers.getlist() 检查基数，不能只取首值或先转 dict。
- 缺失、格式或长度不合法为 422/VALIDATION_ERROR；业务值只有收到且通过校验后才承诺原样保存，格式校验位于创建事务之前。
- 网络解析可能先剥离字段值两端 OWS；NUL 等非法报文可能由 Uvicorn 在进入应用前返回纯文本 400，不能要求统一 422 错误体，也不能恢复上游已丢失的原始字节。
- [主本第 1192 行](https://github.com/yuliang-1234567/Online-Judge-platform/blob/712aead1e5c515f4112324fc1e9bb8a423576c83/docs/project-design.md#L1192) 完整规定请求头契约；[第 965 行](https://github.com/yuliang-1234567/Online-Judge-platform/blob/712aead1e5c515f4112324fc1e9bb8a423576c83/docs/project-design.md#L965) 仅同步原句尾。字符集不由 utf8mb4_0900_bin 反推。

## 框架证据（本地源码静态阅读）

下列包内路径以 backend/.venv/lib/python3.12/site-packages/ 为根；它们是本地依赖证据，不是仓库跟踪文件，也不是 HTTP 链路实测。

| 已安装版本 | 包内源码与结论 |
| --- | --- |
| FastAPI 0.147.0 | fastapi/dependencies/utils.py:749：普通标量 Header 走 get，列表走 getlist；标量声明不能证明头唯一。 |
| Starlette 1.9.0 | starlette/datastructures.py:552、559：getlist 取全部匹配值，取单值路径返回首个；按 Latin-1 解码，不主动 trim 或拆逗号。 |
| h11 0.16.0 | h11/_abnf.py:63、h11/_readers.py:64：提取字段值时排除两端 OWS；_readers.py:43 处理旧式折行。 |
| Uvicorn 0.54.0 | uvicorn/protocols/http/h11_impl.py:182、299：h11 解析异常可在应用前产生纯文本 400。 |

- h11/_abnf.py:55 未排除所有控制字节；不能依赖服务器代替白名单校验。拒绝字符与可接受字符的业务规则由用户裁决。
- [应用路由注册](../../backend/app/main.py) 第 55—59 行未挂接提交路由；提交接口及 key OpenAPI 尚未挂接，本轮未启动应用或生成 OpenAPI。

## 保留前提与迁移边界

- 保留既定 JSON 口径（原 A）：语法错误 422/VALIDATION_ERROR，其他通用请求体解析异常可能 400/HTTP_ERROR；它与协议解析层纯文本 400 分开。
- 不重开四项已批决定：事务协议及父锁后一次补查；列级 utf8mb4_0900_bin 与原样保存；重放不主动入队、由补偿负责；MVP 无幂等 TTL/自动清理、随记录保留且不承诺永久。详见 W5-1a 与设计主文档。
- utf8mb4_0900_bin 是已批目标列级规则，不表示目标数据库已完成迁移；目标 MySQL、实际排序规则、既有 key 和回退冲突仍须独立核查。
- 列级新迁移与 schema guard 演进另开小节，保留 0001 首版；不改整表或 username，不直接放宽守卫、不自动改 key 或回填。
- §9 范围仍为 686—981（296 行）；schema_v1.json 第 5—7 行固定范围，test_schema_check.py 第 286/322/332 行读取。九段 DDL、DDL 指纹及 D: 出处均保持不变。
- W5-1b 只定 key；body.status 与 COMMIT 具体应答/确认契约仍待后续，本轮不展开或收口。

## 证据与验证边界

- 本轮重读 git show 712aead --stat，结果为单文件 2 insertions(+)、2 deletions(-)；--numstat 为 2/2。
- git diff --check 712aead^ 712aead -- docs/project-design.md：退出 0，无输出；父提交 c13940f 与主本快照的 §9 范围、九段 DDL、124 个出处行均一致。
- 主本及本次补记均按用户要求未跑 Ruff/pytest、未连库、未操作容器；未做真实客户端/代理/HTTP 解析链路或幂等接口验证，不记为测试通过。

## 学习与 AI 使用（待掌握）

- 我理解了什么：待用户本人补充；用户批准契约不等于独立理解验收通过。
- 哪里没懂/待补：原样保存与 OWS 的层级、get/getlist 的重复信息差异、应用 422 与协议层 400 的界限；未复述或独立复现的部分继续待掌握。
- 复核关注的坑：标量 Header 取首值、dict 丢重复项、Latin-1 与 UTF-8 混用，以及把解析后的 ASGI 头当成原始报文；这是静态推演，不是故障实测。
- 为什么选当前方案：用户选择 ASCII 白名单并统一拒绝空白、重复头和逗号，保留大小写与业务值；可打印 ASCII/Unicode、允许内部空格或同值重复均未采用。
- AI 使用记录：AI 提供源码证据、候选与场景并起草本文；用户裁决 C1/S1/D1、批准两行落盘及本次 B 归属；没有新增实现或代写掌握结论。

## 记录状态

- 本文件本轮仅新建，未暂存、提交或推送；待用户审阅 diff 后，单独按流程提交、推送，不与 W5-1a 记录合并。
- 补记归属、M1 已收口及 7df7f83 历史例外、后续 W5-1c/W5-1d 一主一记录安排见 [W5-1a 记录](w5-1a-design.md)；两条记录完成后再排后续小节。
