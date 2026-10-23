# 每日自测题

用途：把每天的改动变成可以自测的问题。答不上来说明那块没读透，比通读一遍有用。

分工：DSH 复核方出题 → Codex 落盘并审核 → 用户作答 → DSH 批改，答案与批注由 Codex 写回该题下方。

题目合格线（Codex 每次审核按此判）：

1. 行号可验证：每条「读哪里」必须是 path:行—行，且这些行确实包含题目所指内容。
2. 戳中当天改动：每题标注「对应改动」，指向当天至少一个提交；无提交时写「范围：未提交文件」或「复习 某日」。
3. 可判分：答案能用对/错/半对判定，不接受开放题。

约定：每天一节 ## YYYY-MM-DD，每天 4—5 题；每题 ### Qn｜短标题（N 分钟）；只追加不改历史题；当天没有实质提交就不出题；文件超过 400 行时另建 daily-questions-2.md 并互相链接；作答后把题末未答复选框标记为已完成。

## 2026-10-19

### Q1｜为什么端口是 13306 / 16379（3 分钟）

- 对应改动：4ecde79（dev Compose 与 Makefile）
- 问：这两个宿主端口分别对应容器里的什么端口？为什么加 127.0.0.1: 前缀？去掉会怎样？
- 读哪里：deploy/docker-compose.dev.yml:17—19、deploy/docker-compose.dev.yml:43—45、AGENTS.md:63
- 及格线：能说出 宿主:容器 的方向，以及回环绑定挡掉了什么。
- [ ] 已答

### Q2｜/healthz 为什么这么"空"（3 分钟）

- 对应改动：f71c890、b52f128（后端骨架与依赖）
- 问：它返回什么？为什么不去查数据库和 Redis？如果查了会有什么后果？
- 读哪里：backend/app/main.py:8—11、backend/tests/api/test_healthz.py:6—12、README.md:10、docs/evidence/06.4-local-checks.md:52—60
- 及格线：能区分"进程活着"与"依赖都活着"。
- [ ] 已答

### Q3｜CI 到底跑了哪几步（4 分钟）

- 对应改动：f27c93e（Ruff 提交检查与最小 CI）
- 问：job 名是什么？四个 run 步骤分别做什么？没有起 MySQL 为什么也能过？select = ["E","F","I","B","UP"] 各防什么（说三个即可）？
- 读哪里：.github/workflows/ci.yml:15—40、backend/pyproject.toml:14—16、backend/pyproject.toml:22—23
- 及格线：知道 CI 只做不需要外部服务的验证。
- [ ] 已答

### Q4｜环境模板与真实配置怎么分开（3 分钟）

- 对应改动：b34da9e（仓库规则与环境变量模板）
- 问：.env 为什么不入库、.env.example 为什么必须入库？哪一行保证「模板能进、真实配置进不去」，它和 .env.* 谁先生效？
- 读哪里：deploy/.env.example:6—10、.gitignore:8—11
- 及格线：能说出 !.env.example 这条否定规则排在 .env.* 之后才生效。
- [ ] 已答

## 2026-10-20

### Q1｜06.5 探针验证了什么、没验证什么（4 分钟）

- 对应改动：dd32e92（探针实现）、e11d673（结果记录）
- 问：它验的是哪几段链路？明确没验证什么？为什么"容器直连 PyPI 返回 200"不等于"镜像构建可用"？
- 读哪里：docs/modules/worker-probe.md:3—6、docs/modules/worker-probe.md:33—38、docs/learning/06.5-worker-probe.md:21、docs/learning/06.5-worker-probe.md:51、docs/adr/ADR-016-wsl-development-environment.md:38—44、docs/adr/ADR-016-wsl-development-environment.md:56—60
- 及格线：能说出"文件与权限链路通"和"判题沙箱就绪"是两件事。
- [ ] 已答

### Q2｜skill 为什么要挪进 .agents/skills（3 分钟）

- 对应改动：dbbf3d1（skill 移入）、a25f88b（加载验证记录）
- 问：放别处为什么不生效？Codex 靠哪几层机制决定读不读、什么时候读？SKILL.md 开头三行（---、name:、description:）分别给谁看？
- 读哪里：AGENTS.md:6—12、.agents/skills/git-push-workflow/SKILL.md:1—4、.agents/skills/git-push-workflow/SKILL.md:33—55、docs/learning/skills-codex-loading.md:6—35
- 及格线：能分清三层：目录扫描发现 skill → name/description 决定要不要读 → AGENTS 触发表规定什么时候必须读正文。只答"AGENTS 触发"不给分。
- [ ] 已答

### Q3｜代理端口为什么不写死（3 分钟）

- 对应改动：47daa7b（代理探活规则与验收记录）
- 问：为什么禁止从文档里抄代理端口？探活为什么必须与联网命令在同一次操作里做？三种用途的判据各是多少？
- 读哪里：AGENTS.md:25—45
- 及格线：能复述 200 / 200 / 401 三条判据。
- [ ] 已答

### Q4｜验收拿什么当证据（4 分钟）

- 对应改动：dd32e92（Worker 环境探针）
- 问：为什么「路径相同」或「root 也能写」都不足以验收？三个场景各要拿出哪几样证据？
- 读哪里：docs/modules/worker-probe.md:19—21、docs/modules/worker-probe.md:49—50
- 及格线：答不出 SHA-256、实际 UID/GID、输出属主三者中的至少两样即为错。
- [ ] 已答

## 2026-10-21

### Q1｜"小节"到底怎么划（5 分钟）

- 对应改动：29b47d6、279b242（小节级粒度规则）
- 问：一个小节最多几个提交、分哪两类、为什么分开？为什么一次 push 可以含多个 commit？什么信号说明小节划大了？
- 读哪里：.agents/skills/git-push-workflow/SKILL.md:56—71、AGENTS.md:71、README.md:9—16
- 及格线：能说出主本与记录的区分，以及"另外/顺便补第二件事"就是跨小节。
- [ ] 已答

### Q2｜risk-checkpoint 现在管哪三件事（5 分钟）

- 对应改动：e1b8148、de1c3a1（新增 skill 与审要求一节）、21804f0（质疑纪律与风险分档）
- 问：它要求在什么三个时点做什么？为什么用户要求不合理时不能直接照做？哪两类情况必须等二次确认？哪些东西不该列进拍板点？
- 读哪里：.agents/skills/risk-checkpoint/SKILL.md:10—28、.agents/skills/risk-checkpoint/SKILL.md:29—52、.agents/skills/risk-checkpoint/SKILL.md:53—81
- 及格线：能说出三个时点（开工前审要求、执行中质疑、收尾列风险）与硬停线（事实性错误、不可逆操作），并能说出风险分两档、必须现在定的不设上限。
- [ ] 已答

### Q3｜12 项决策里哪些动了表结构（5 分钟）

- 对应改动：4e7df7f、5e7ccb6、cf33535（核对、设计同步、状态记录）
- 问：哪几项改了 DDL、哪几项只改文档或图？为什么第 4 项和第 9 项要拆成两个决策？以设计文档中的 DDL 文本为准；此时的迁移尚未执行。
- 读哪里：docs/learning/open-questions.md:19—38、docs/evidence/db-schema-check.md:91—183、docs/evidence/db-schema-check.md:184—195、docs/project-design.md:710—908、docs/project-design.md:909—934
- 及格线：知道"可空性"与"有没有外键"是正交的两件事。
- [ ] 已答

### Q4｜边界声明和观察项各防什么（6 分钟）

- 对应改动：9c3b670（章节边界声明）、31ca49f（结构观察项）
- 问：§9 开头的边界声明给谁划界、和 §9.1 第一条约定什么关系？观察项的四条触发条件是什么？现在占全文多少、为什么还不拆？
- 读哪里：docs/project-design.md:686—692、docs/project-design.md:692—709、docs/learning/open-questions.md:62—64
- 及格线：能说出"防别处重复定义"与"防章节长到该拆时没人发现"。
- [ ] 已答

## 2026-10-22

### Q1｜users 表的五个空（4 分钟）

- 对应改动：范围：未提交（backend/alembic/versions/0001_initial_schema.py）
- 问：迁移文件目前只有注释和 pass；按注释块里的类型映射规则，users.username VARCHAR(32) 应写成哪种 sa.* 类型、created_at DATETIME(3) 的 server_default 要带什么？
- 读哪里：backend/alembic/versions/0001_initial_schema.py:5—14、docs/project-design.md:715—724
- 及格线：sa.String(32) 与 server_default=sa.text("CURRENT_TIMESTAMP(3)") 两点全对才算过。
- [ ] 已答

### Q2｜哪两张表没有时间列（3 分钟）

- 对应改动：复习 07.3（fa35097）
- 问：九张表里哪两张没有 DATETIME 列？为什么可以不写？
- 读哪里：docs/project-design.md:807—823、docs/project-design.md:876—883
- 及格线：能说出纯关联表与"时间记在父行"这两种理由。
- [ ] 已答

### Q3｜两个外键为什么删法不同（4 分钟）

- 对应改动：复习 07.3（fa35097）
- 问：submission_cases 的两个外键，为什么一个是 ON DELETE CASCADE、一个是 ON DELETE SET NULL？这和 case_index 有什么关系？
- 读哪里：docs/project-design.md:819—820、docs/project-design.md:807—818
- 及格线：能说出子行"离开父行还站不站得住"。
- [ ] 已答

### Q4｜离线渲染验证了什么（4 分钟）

- 对应改动：范围：未提交文件（backend/alembic/）
- 问：alembic upgrade head --sql 为什么不连数据库也能生成 SQL？它能验证什么、不能验证什么？
- 读哪里：backend/alembic/env.py:33—44、backend/alembic/env.py:73—76
- 及格线：能说明 --sql 只生成 SQL、不交给 MySQL 解析，因此可检查 SQL 生成与类型映射，不能证明数据库语法接受、真实执行或约束冲突。
- [ ] 已答

## 2026-10-23

### Q1｜类型与默认值能不能顺手简化（5 分钟）

- 对应改动：8e74434（九表首版迁移与离线结构验证）
- 问：① id 的无符号属性、DATETIME 的毫秒精度分别由哪个 mysql 类型参数保留？② role 的字符串默认值与 created_at 的数据库表达式为何不能混写，updated_at 的 ON UPDATE 写在哪里？③ 给 submissions.queued_at 顺手加 CURRENT_TIMESTAMP(3) 默认值，是否仍符合本次迁移？
- 读哪里：`backend/alembic/versions/0001_initial_schema.py:12—19`、`backend/alembic/versions/0001_initial_schema.py:34—54`、`backend/alembic/versions/0001_initial_schema.py:208—219`
- 及格线：三小问均正确且能指出相应声明为对；只答对一至两问为半对；三问均错为错。
- [ ] 已答

### Q2｜列集合相同就算约束相同吗（5 分钟）

- 对应改动：8e74434（复合主键、幂等唯一约束及列序测试）
- 问：① 按顺序写出 user_problem_stats 与 problem_tags 的主键列，以及 uk_sub_user_idempotency 的列组合。② 两张复合主键表的主键列能否照抄 users.id 的 autoincrement=True？③ 对照本次独立基线，列集合相同但列序反了，测试应不应该放行？指出测试怎样保留顺序。
- 读哪里：`backend/alembic/versions/0001_initial_schema.py:221—224`、`backend/alembic/versions/0001_initial_schema.py:251—284`、`backend/alembic/versions/0001_initial_schema.py:290—301`、`backend/tests/test_schema_check.py:843—859`
- 及格线：三小问均正确为对；一至两问正确为半对；都错为错。第一问的三个列组必须全部与基线顺序一致，才算该小问正确。
- [ ] 已答

### Q3｜先建什么、先删什么（6 分钟）

- 对应改动：8e74434（step2 索引、step3 外键与逆序 downgrade）、9c7a7ef（回退边界记录）
- 问：① 普通索引和外键各在哪一步创建、各有多少条？downgrade 按什么类别顺序删除，第一张与最后一张删除的业务表分别是什么？② fk_sc_sub 与 fk_sc_case 的 ondelete 分别是什么，后者要求 test_case_id 满足什么可空条件，两者 onupdate 是什么？③ 为什么不能先删外键依赖的索引？重新 upgrade 能否恢复已被 drop_table 删除的数据？
- 读哪里：`backend/alembic/versions/0001_initial_schema.py:331—337`、`backend/alembic/versions/0001_initial_schema.py:409—417`、`backend/alembic/versions/0001_initial_schema.py:230—245`、`backend/alembic/versions/0001_initial_schema.py:459—477`、`backend/alembic/versions/0001_initial_schema.py:541—599`、`docs/learning/07.4-initial-schema.md:31—35`
- 及格线：三小问全部正确为对；一至两问正确为半对；全部错误为错。把结构重建等同于数据恢复，第三问直接判错。
- [ ] 已答

### Q4｜怎样证明语义测试不是假绿（6 分钟）

- 对应改动：8e74434（离线列语义测试）、9c7a7ef（两次反例与还原证据）
- 问：① Recorder 接替了哪个对象，调用 upgrade 后从哪里拿实际列定义？它需要 Engine 或数据库连接吗？② 比较前对 INTEGER/int、带引号的字符串默认值、带 ON UPDATE 的时间表达式分别做什么归一化？③ 把 audit_logs.resource_type 的 32 改成 16、给 submissions.queued_at 增加默认值，分别应在哪个比较项失败？两次故意改错后，为什么还要核对迁移文件前后 SHA-256？
- 读哪里：`backend/tests/test_schema_check.py:809—842`、`backend/tests/test_schema_check.py:860—890`、`docs/learning/07.4-initial-schema.md:8—11`
- 及格线：三小问全部正确为对；一至两问正确为半对；全部错误为错。第二问须说全三种归一化，第三问须分别指出两种错误及还原校验的作用。
- [ ] 已答

### Q5｜离线全绿后，哪些结论仍不能下（5 分钟）

- 对应改动：8e74434（离线渲染禁连接测试）、9c7a7ef（实库未验证边界）
- 问：① --sql 路径怎样在不创建 Engine 的情况下生成迁移文本，测试用什么办法让意外建 Engine 或连接直接失败？② 逐项判断“SQL 已能生成”“MySQL 已接受并执行”“真实 charset/collation 已验证”“四条自动外键支撑索引已实测”能否由本次离线通过推出。③ 列出后续实库轮要确认的四个自动索引列，并说明为何它们不能直接计成离线 SQL 漏写的四个普通索引。
- 读哪里：`backend/alembic/env.py:33—44`、`backend/tests/test_schema_check.py:900—904`、`docs/learning/07.4-initial-schema.md:39—40`、`backend/tools/check_db_schema.py:228—241`
- 及格线：三小问全部正确为对；一至两问正确为半对；全部错误为错。第二问必须逐项判断，第三问必须列全四处并区分索引用途。
- [ ] 已答
