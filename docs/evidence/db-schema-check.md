# 数据库表与 ER 核对（2026-10-21；07.4 更新 2026-10-23）

基线：主本提交 8e74434。D = [project-design.md](../project-design.md)，E = [er.md](../figures/er.md)；下文 D/E 后的数字均为该提交中这两个文件的一基行号。
范围：重读 D:686–981、312–326、1943–1954 与 E:1–125；逐表按 CREATE TABLE 和字段名重新定位，未沿用旧行号偏移。
裁定分层：设计已落地；首版迁移已实现并通过离线验证；数据库未建、未在真实 MySQL 执行。API、UTC 会话配置与业务约束仍须各自验收。
12 项决定及历史候选见 [数据库核对决策清单](../learning/open-questions.md#数据库核对决策清单)；离线命令与理解检查见 [07.4 学习记录](../learning/07.4-initial-schema.md)。

## A 表清单

共 9 张基础表，9 张均有 CREATE TABLE，合计 84 列；tags、problem_tags、audit_logs 已有完整 DDL。D:969–981 的分析只读视图规划不计入基础表数量。

| 表名 | 一句话职责 | 设计章节 | 出处行号 | 有无 DDL |
| --- | --- | --- | --- | --- |
| users | 保存账号、密码摘要、角色与账号状态。 | §9.2.1；附录 B | D:715–724、1943 | 有，起始 D:715 |
| problems | 保存题目内容、发布状态、资源限制与创建人。 | §9.2.1；附录 B | D:728–743、1944 | 有，起始 D:728 |
| test_cases | 保存测试点、样例标记、输入与期望输出。 | §9.2.2；附录 B | D:749–763、1944、1953 | 有，起始 D:749 |
| submissions | 保存提交、结果、限制快照及恢复记录。 | §9.2.3；附录 B | D:769–803、1945–1948、1951 | 有，起始 D:769 |
| submission_cases | 保存逐测试点结果及快照。 | §9.2.3；附录 B | D:807–821、1946–1947 | 有，起始 D:807 |
| user_problem_stats | 保存用户对题目的统计及首次通过引用。 | §9.2.4；附录 B | D:829–841、1945、1949 | 有，起始 D:829 |
| tags | 保存题目标签及唯一名称。 | §9.2.4；附录 B | D:867–872、1944 | 有，起始 D:867 |
| problem_tags | 保存题目与标签的多对多关联。 | §9.2.4；附录 B | D:876–883、1944 | 有，起始 D:876 |
| audit_logs | 保存管理员操作及资源摘要。 | §9.2.4；附录 B | D:887–900、1952 | 有，起始 D:887 |

## B ER 对照

### 9 个实体

逐表核对结果：ER 与设计 DDL 的字段名及列序一致。图仍不替代类型长度、unsigned、可空性、默认值、复合约束列序与引用动作的 SQL 定义。

| 实体 | 设计侧 | ER 侧 | 裁定与边界 |
| --- | --- | --- | --- |
| users | D:715–724 | E:19–27 | 字段一致；设计已落地，数据库未建。 |
| problems | D:728–743 | E:28–40 | 字段一致；设计已落地，数据库未建。 |
| test_cases | D:749–763 | E:41–53 | 字段一致；设计已落地，数据库未建。 |
| submissions | D:769–803 | E:54–79 | 字段一致；设计已落地，数据库未建。 |
| submission_cases | D:807–821 | E:80–91 | 字段一致；设计已落地，数据库未建。 |
| user_problem_stats | D:829–841 | E:92–100 | 字段一致；设计已落地，数据库未建。 |
| tags | D:867–872 | E:101–105 | 字段一致；设计已落地，数据库未建。 |
| problem_tags | D:876–883 | E:106–109 | 字段一致；设计已落地，数据库未建。 |
| audit_logs | D:887–900 | E:110–120 | 字段一致；设计已落地，数据库未建。 |

### 12 条关系

原记录的 11 条关系已包含在当前图中；另有首次 AC 引用（E:18），合计 12 条物理外键对应关系。基数意图不替代实际约束或应用校验。

| # | 关系及边界 | 设计侧依据 | ER 侧行号 | 裁定 |
| --- | --- | --- | --- | --- |
| 1 | users → problems：每题恰属一个创建人，用户可创建零至多题。 | 列 D:737；FK D:742 | E:7、37 | 设计已落地；数据库未建。 |
| 2 | users → submissions：每次提交恰属一个用户。 | 列 D:771；FK D:801 | E:8、56 | 设计已落地；数据库未建。 |
| 3 | problems → submissions：每次提交恰属一道题。 | 列 D:772；FK D:802 | E:9、57 | 设计已落地；数据库未建。 |
| 4 | problems → test_cases：每个测试点恰属一道题。 | 列 D:751；FK D:762 | E:10、43 | 设计已落地；数据库未建。 |
| 5 | submissions → submission_cases：每条明细恰属一次提交。 | 列 D:809；FK D:819 | E:11、82 | 设计已落地；数据库未建。 |
| 6 | test_cases → submission_cases：明细可对应零或一个测试点。 | 列 D:810；FK D:820 | E:12、83 | 设计已落地；数据库未建。 |
| 7 | users → user_problem_stats：每条统计恰属一个用户。 | 列 D:830；FK D:838 | E:13、93 | 设计已落地；数据库未建。 |
| 8 | problems → user_problem_stats：每条统计恰属一道题。 | 列 D:831；FK D:839 | E:14、94 | 设计已落地；数据库未建。 |
| 9 | problems → problem_tags：每条关联恰属一道题。 | 列 D:877；FK D:881 | E:15、107 | 设计已落地；数据库未建。 |
| 10 | tags → problem_tags：每条关联恰属一个标签。 | 列 D:878；FK D:882 | E:16、108 | 设计已落地；数据库未建。 |
| 11 | users → audit_logs：每条审计引用一个非空管理员操作者。 | 列 D:889；FK D:899 | E:17、112 | 设计已落地；数据库未建。 |
| 12 | submissions → user_problem_stats：首次 AC 引用可空；同用户、同题目与 ACCEPTED 由应用层校验。 | 列 D:835；FK D:840 | E:18、98 | 设计已落地；数据库未建。 |

### 每张表的三类字段差集

以当前基线重算，九表均无字段名差集；旧记录中遗漏的时间、difficulty、统计及排队字段已补齐。E:3 说明图的维护范围，E:125 说明类型与约束以设计为准。

| 表 | ER 有意省略（逐字段明示） | 设计有而 ER 无 | ER 有而设计无 |
| --- | --- | --- | --- |
| users | 无字段名差集 | 无 | 无 |
| problems | 无字段名差集 | 无 | 无 |
| test_cases | 无字段名差集 | 无 | 无 |
| submissions | 无字段名差集 | 无 | 无 |
| submission_cases | 无字段名差集 | 无 | 无 |
| user_problem_stats | 无字段名差集 | 无 | 无 |
| tags | 无字段名差集 | 无 | 无 |
| problem_tags | 无字段名差集 | 无 | 无 |
| audit_logs | 无字段名差集 | 无 | 无 |

audit_logs.payload_summary 当前是 VARCHAR(2048)（D:893，E:116），原“文字表类型待确认”的结论已过期；字符集、排序规则仍未做实库验收。

### 9 条候选疑点的复核结论

| 候选 | 当前设计事实 | 实现与验收状态 |
| --- | --- | --- |
| 1 | 九表均有 DDL，起始行见 A；原“六表 DDL、三表文字”口径已过期。 | 设计已落地；九表迁移离线通过，数据库未建。 |
| 2 | 两列 status 都是 VARCHAR(20)，明细完整名称见 D:813、824；提交状态见 D:312–321。 | 设计已落地；枚举与业务写入未验收，不能由列长度证明。 |
| 3 | 当前 ER 与九表字段名和列序一致，见本节差集。 | 设计与图已落地；不替代数据库结构验收。 |
| 4 | 六个非主键唯一约束均有 DDL，§9.3 已分栏列全（D:915–920）。 | 迁移声明及列序已离线核对；真实冲突行为未验证。 |
| 5 | tags、problem_tags、audit_logs 完整 DDL 见 D:867–900；audit_logs.user_id 非空见 D:889。 | 设计已落地；迁移离线通过，数据库未建。 |
| 6 | MySQL 服务器与所有写入会话统一 UTC 已写入 D:702；D:652 是 Celery 设置。 | 设计已落地；未核验服务器或连接会话配置。 |
| 7 | first_ac_submission_id 可空（D:835），外键已定义（D:840），业务条件见 D:844。 | 迁移已含外键；同用户、同题目与 ACCEPTED 的应用校验未实现验收。 |
| 8 | language 注释为 python（D:773），首版允许值及拒绝规则见 D:824。 | 设计已落地；提交接口与 OpenAPI 校验未验收。 |
| 9 | 明细仅保存六个逐点终态，编译失败不产生明细（D:813、824）。 | 设计已落地；实际判题与持久化行为未验收。 |

## C 约束清单

### 主键

九张 DDL 均声明 InnoDB 与 utf8mb4；复合主键不自增。以下是设计与迁移声明的离线核对结果，不表示数据库已存在。

| 表 | 主键 | 设计依据 | ER 依据 |
| --- | --- | --- | --- |
| users | (id) | D:716；列序以 DDL 为准 | E:20 |
| problems | (id) | D:729；列序以 DDL 为准 | E:29 |
| test_cases | (id) | D:750；列序以 DDL 为准 | E:42 |
| submissions | (id) | D:770；列序以 DDL 为准 | E:55 |
| submission_cases | (id) | D:808；列序以 DDL 为准 | E:81 |
| user_problem_stats | (user_id, problem_id) | D:837；列序以 DDL 为准 | E:93、94 |
| tags | (id) | D:868；列序以 DDL 为准 | E:102 |
| problem_tags | (problem_id, tag_id) | D:879；列序以 DDL 为准 | E:107、108 |
| audit_logs | (id) | D:888；列序以 DDL 为准 | E:111 |

### 外键及引用动作

12 条外键均为“设计已落地、数据库未建”；迁移已通过 AST 与离线渲染验证。只有 fk_sc_sub 删除 CASCADE、fk_sc_case 删除 SET NULL，其余删除 RESTRICT；全部更新 RESTRICT。

| 约束 | 子表列 → 目标列 | ON DELETE | ON UPDATE | 设计依据 |
| --- | --- | --- | --- | --- |
| fk_problems_creator | problems.created_by → users.id | RESTRICT | RESTRICT | D:742 |
| fk_cases_problem | test_cases.problem_id → problems.id | RESTRICT | RESTRICT | D:762 |
| fk_sub_user | submissions.user_id → users.id | RESTRICT | RESTRICT | D:801 |
| fk_sub_problem | submissions.problem_id → problems.id | RESTRICT | RESTRICT | D:802 |
| fk_sc_sub | submission_cases.submission_id → submissions.id | CASCADE | RESTRICT | D:819 |
| fk_sc_case | submission_cases.test_case_id → test_cases.id | SET NULL | RESTRICT | D:820 |
| fk_ups_user | user_problem_stats.user_id → users.id | RESTRICT | RESTRICT | D:838 |
| fk_ups_problem | user_problem_stats.problem_id → problems.id | RESTRICT | RESTRICT | D:839 |
| fk_ups_first_ac_submission | user_problem_stats.first_ac_submission_id → submissions.id | RESTRICT | RESTRICT | D:840 |
| fk_problem_tags_problem | problem_tags.problem_id → problems.id | RESTRICT | RESTRICT | D:881 |
| fk_problem_tags_tag | problem_tags.tag_id → tags.id | RESTRICT | RESTRICT | D:882 |
| fk_audit_logs_user | audit_logs.user_id → users.id | RESTRICT | RESTRICT | D:899 |

fk_sc_case 的引用列可空（D:810），删除测试点后仍由 case_index/is_sample 快照保留明细身份（D:811–812、858）。
首次 AC 外键只保证引用记录存在，不能代替同用户、同题目及 ACCEPTED 校验（D:844，E:125）。§9.1 的原因说明 D:708 不替代逐条引用动作。
设计内联外键，迁移在 step3 后置 ALTER；这是 SQL 呈现差异，声明的最终结构一致，实际执行仍未验证。
4 条 MySQL 自动外键支撑索引（problems.created_by、submission_cases.test_case_id、user_problem_stats.problem_id、first_ac_submission_id）未在离线 SQL 中手建；实际生成与复用留给实库核对。

### 唯一约束（不把主键重复计数）

| 表/约束名 | 唯一列组 | 定义出处 | ER 对照 |
| --- | --- | --- | --- |
| users / uk_users_username | (username) | D:723，DDL | E:21 |
| problems / uk_problems_slug | (slug) | D:740，DDL | E:30 |
| test_cases / uk_cases_problem_idx | (problem_id, case_index) | D:761，DDL | E:123 |
| submissions / uk_sub_user_idempotency | (user_id, idempotency_key) | D:794，DDL | E:123 |
| submission_cases / uk_sc_sub_idx | (submission_id, case_index) | D:818，DDL | E:123 |
| tags / uk_tags_name | (name) | D:871，DDL | E:103 |

六个非主键唯一约束均有完整 DDL；§9.3 D:915–920 已列全。幂等键为 (user_id, idempotency_key) 联合唯一（D:794、918，E:123），不是 idempotency_key 单列唯一。
10 个服务查询的普通索引已在迁移 step2 显式创建；MySQL 自动外键支撑索引不计入这 10 个，实际索引结构与复用未验收。

### 时间与语言的已拍板口径

时间依据：D:702、979 约定 DATETIME(3)/UTC，默认及 ON UPDATE 逐列见各表 DDL；Celery 的 D:652 不能证明 MySQL 时区。设计已落地，服务器及全部写入会话仍未核验。
已选服务器与连接会话 UTC；“由应用统一生成时间”保留为历史未选方案，不改当前默认值与 ON UPDATE 声明。
语言依据：D:773 注释仅 python，D:824 规定拒绝 cpp 及未知值；设计已落地，接口校验尚未验收。

### 10 个状态与两列 status 的对应关系

提交状态定义见 D:312–321，默认 QUEUED 见 D:777；明细的六个逐点终态见 D:813、824。VARCHAR 不会自动执行枚举或状态迁移约束。

| 状态（§5.3） | submissions.status | submission_cases.status |
| --- | --- | --- |
| QUEUED | 明确，D:312 | 不作为明细状态。 |
| RUNNING | 明确，D:313 | 不作为明细状态。 |
| ACCEPTED | 明确，D:314 | 设计允许的逐点终态；运行行为未验收。 |
| WRONG_ANSWER | 明确，D:315 | 设计允许的逐点终态；运行行为未验收。 |
| COMPILE_ERROR | 明确，D:316 | 不保存；编译失败无逐点明细。 |
| RUNTIME_ERROR | 明确，D:317 | 设计允许的逐点终态；运行行为未验收。 |
| TIME_LIMIT | 明确，D:318 | 设计允许的逐点终态；运行行为未验收。 |
| MEMORY_LIMIT | 明确，D:319 | 设计允许的逐点终态；运行行为未验收。 |
| OUTPUT_LIMIT | 明确，D:320 | 设计允许的逐点终态；运行行为未验收。 |
| FAILED | 明确，D:321 | 不作为明细状态。 |

完整状态名最长 13 字符，两个 VARCHAR(20) 均可容纳（D:777、813）；长度足够不表示枚举校验已实现。
test_cases.updated_at 已定义（D:760）；历史结果保留、不重判及快照语义见 D:858，旧输入/期望输出不可还原的 M1 限制见 D:862。

## M1 验收要点

以下均为尚未通过的实库或业务验收，不把离线通过当作数据库/API 已通过。

- 真实 MySQL 执行 upgrade → downgrade → upgrade，核对九表、列定义、六个唯一约束、10 个普通索引与 12 条外键；降级会删除表和数据，不是数据恢复。
- 核验 charset/collation、4 条自动外键支撑索引、复用关系与 UTC 服务器/连接会话。
- 验证两种特殊删除动作、其余 RESTRICT、唯一冲突及可空引用行为。
- 应用层验证 python 范围、完整状态枚举、编译失败无逐点明细及管理员审计身份。
- 首次 AC 引用分别拒绝跨用户、跨题目与非 ACCEPTED，不能只检查目标记录存在。
- 测试数据修改仍保留历史结果；展示不得把当前测试数据称为提交时原始数据。
- 五项理解检查与关闭 AI 后复现尚未验收，参考答案不代表用户已掌握。
