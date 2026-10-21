# 数据库表与 ER 核对（2026-10-21）

基线：本地提交 bb8f0c3。D = [project-design.md](../project-design.md)，E = [er.md](../figures/er.md)；下文 D/E 后的数字均为这两个文件的一基行号。
范围：已读 D:686–913、304–326、1867–1884 与 E:1–104，并核对全文时间设置及语言范围。记录核对基线与 M1 已拍板待落地口径；未修改来源、未写迁移、未建表、未执行 SQL。
裁定口径：“一致”表示原文能互相印证；“已拍板（M1 落地）”表示用户已确认口径、实现及验收尚未执行。D/E 行号及原文事实仍以核对基线为准，不能将 M1 决定说成原设计或数据库已更新。完整选项与决定见 [数据库核对决策清单](../learning/open-questions.md#数据库核对决策清单)；三张文字表的具体字段参数仍待 M1 严格级设计确认。

## A 表清单

共 9 张基础表：6 张有 CREATE TABLE，3 张仅有文字表。D:836–837 是表头，三张文字表实际位于 D:838–840；分析视图 D:900–912 不计入基础表数量。

| 表名 | 一句话职责 | 设计章节 | 出处行号 | 有无 DDL |
| --- | --- | --- | --- | --- |
| users | 保存账号、密码摘要、角色与账号状态。 | §9.2.1；附录 B FR-01 | D:711–720、1873 | 有，起始 D:711 |
| problems | 保存题目内容、发布状态、资源限制与创建人。 | §9.2.1；附录 B FR-02 | D:724–739、1874 | 有，起始 D:724 |
| test_cases | 保存题目测试点、样例标记、输入与期望输出。 | §9.2.2；附录 B FR-02/11 | D:745–758、1874、1883 | 有，起始 D:745 |
| submissions | 保存代码提交、判题结果、限制快照与恢复所需记录。 | §9.2.3；附录 B FR-03/04/05/06/09 | D:764–798、1875–1878、1881 | 有，起始 D:764 |
| submission_cases | 保存每次提交的逐测试点结果与测试点快照。 | §9.2.3；附录 B FR-04/05 | D:802–816、1876–1877 | 有，起始 D:802 |
| user_problem_stats | 保存用户对题目的提交统计及首次通过信息。 | §9.2.4；附录 B FR-03/07 | D:822–833、1875、1879 | 有，起始 D:822 |
| tags | 保存题目标签及唯一名称。 | §9.2.4；附录 B FR-02 | D:838、1874 | 无，仅文字 |
| problem_tags | 保存题目与标签之间的多对多关联。 | §9.2.4；附录 B FR-02 | D:839、1874 | 无，仅文字 |
| audit_logs | 保存管理操作、资源引用及经过摘要处理的审计内容。 | §9.2.4；附录 B FR-10 | D:840、1882 | 无，仅文字 |

## B ER 对照

### 9 个实体

“一致”只指实体及已有字段定义能对应；字段是否应显示、长度/可空性等未画信息另列，不据此宣称图含完整结构。

| 实体 | 设计侧 | ER 侧 | 裁定与边界 |
| --- | --- | --- | --- |
| users | D:711–720 | E:18–24 | 一致；已拍板（M1 落地）：按 6A 补齐时间字段展示。 |
| problems | D:724–739 | E:25–33 | 一致；已拍板（M1 落地）：按 6A 补齐 difficulty 等字段。 |
| test_cases | D:745–758 | E:34–44 | 一致；已拍板（M1 落地）：按 6A 补齐创建时间展示，8A 增加更新时间的口径另见 C。 |
| submissions | D:764–798 | E:45–60、102 | 一致；已拍板（M1 落地）：按 6A 补齐统计、排队及其余缺项，1A 仅允许 python。 |
| submission_cases | D:802–816 | E:61–72、102 | 一致；已拍板（M1 落地）：2A/10A 使用六个完整逐点终态，编译失败无明细。 |
| user_problem_stats | D:822–833 | E:73–80、102 | 一致；已拍板（M1 落地）：6A 补齐更新时间展示，7A 增加首次 AC 引用外键。 |
| tags | D:838 | E:81–84、104 | 已拍板（M1 落地）：5A 在严格级设计补齐 DDL；原文仍无完整 DDL，具体字段类型等参数待该小节确认。 |
| problem_tags | D:839 | E:85–88、104 | 已拍板（M1 落地）：5A 补齐 DDL，12A 明确外键目标及动作；具体字段参数待严格级设计确认。 |
| audit_logs | D:840 | E:89–99、104 | 已拍板（M1 落地）：4B 非空管理员操作者，9A 物理外键，5A 补齐 DDL；其余字段参数待严格级设计确认。 |

### 11 条关系

| # | 关系及 ER 基数 | 设计侧依据 | ER 侧行号 | 裁定 |
| --- | --- | --- | --- | --- |
| 1 | users → problems：每题恰属 1 个创建人，用户可创建 0 至多题 | created_by 非空 D:733；FK D:738 | E:7、32 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 2 | users → submissions：每次提交恰属 1 个用户，用户可有 0 至多次提交 | user_id 非空 D:766；FK D:796 | E:8、47 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 3 | problems → submissions：每次提交恰属 1 题，题目可有 0 至多次提交 | problem_id 非空 D:767；FK D:797 | E:9、48 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 4 | problems → test_cases：每测试点恰属 1 题，题目可有 0 至多测试点 | problem_id 非空 D:747；FK D:757 | E:10、36 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 5 | submissions → submission_cases：每条明细恰属 1 次提交，提交可有 0 至多明细 | submission_id 非空 D:804；FK/级联删除 D:814 | E:11、63 | 一致；已拍板（M1 落地）：ON DELETE CASCADE、ON UPDATE RESTRICT。 |
| 6 | test_cases → submission_cases：明细可对应 0 或 1 个测试点，测试点可被 0 至多明细引用 | test_case_id 可空 D:805；删除置空 D:815、846 | E:12、64、102 | 一致；已拍板（M1 落地）：ON DELETE SET NULL、ON UPDATE RESTRICT。 |
| 7 | users → user_problem_stats：统计行恰属 1 个用户，用户可有 0 至多统计行 | 非空 D:823；联合 PK D:830；FK D:831 | E:13、74、102 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 8 | problems → user_problem_stats：统计行恰属 1 题，题目可有 0 至多统计行 | 非空 D:824；联合 PK D:830；FK D:832 | E:14、75、102 | 一致；已拍板（M1 落地）：ON DELETE RESTRICT、ON UPDATE RESTRICT。 |
| 9 | problems → problem_tags：关联行恰属 1 题，题目可有 0 至多关联行 | D:839 写联合主键及两个外键，未给完整定义 | E:15、86 | 已拍板（M1 落地）：目标 problems.id，ON DELETE / ON UPDATE 均 RESTRICT；完整 DDL 按 5A 补齐。 |
| 10 | tags → problem_tags：关联行恰属 1 标签，标签可有 0 至多关联行 | D:839 写联合主键及两个外键，未给完整定义 | E:16、87 | 已拍板（M1 落地）：目标 tags.id，ON DELETE / ON UPDATE 均 RESTRICT；完整 DDL 按 5A 补齐。 |
| 11 | users → audit_logs：每条审计恰属 1 用户，用户可有 0 至多审计 | D:840 仅列 user_id，未说明可空性及物理 FK | E:17、91 | 已拍板（M1 落地）：user_id 非空并引用 users.id，仅审计已登录管理员操作，删除/更新均 RESTRICT。 |

### 每张表的三类字段差集

E:3 仅声明“只展示核心字段，完整结构以设计第 9 章为准”，未逐字段说明省略意图。下表保留核对基线的完整差集，不反推原作者意图；已拍板（M1 落地）：6A 按设计侧字段差集补齐 ER，本轮尚未改图。
对于三张文字表，只比较已列字段名；差集为空不代表类型、长度、可空性或完整 DDL 已确认。

| 表 | ER 有意省略（逐字段明示） | 设计有而 ER 无 | ER 有而设计无 |
| --- | --- | --- | --- |
| users | 未逐字段明示（E:3）；不擅自归类 | created_at（D:717）；updated_at（D:718） | 无 |
| problems | 未逐字段明示（E:3）；不擅自归类 | description（D:728）；difficulty（D:729）；created_at（D:734）；updated_at（D:735） | 无 |
| test_cases | 未逐字段明示（E:3）；不擅自归类 | created_at（D:755） | 无 |
| submissions | 未逐字段明示（E:3）；不擅自归类 | error_code（D:773）；error_message（D:774）；passed_cases（D:775）；total_cases（D:776）；runtime_ms（D:777）；memory_kb（D:778）；queued_at（D:785）；started_at（D:786）；finished_at（D:787）；created_at（D:788） | 无 |
| submission_cases | 无字段差集 | 无 | 无 |
| user_problem_stats | 未逐字段明示（E:3）；不擅自归类 | updated_at（D:829） | 无 |
| tags | 无字段差集 | 无 | 无 |
| problem_tags | 无字段差集 | 无 | 无 |
| audit_logs | 无字段差集 | 无 | 无 |

已拍板（M1 落地）：6A 补齐设计侧字段差集。核对基线中 problems.difficulty 缺于 E:25–33（D:729）；submissions.passed_cases、total_cases、queued_at 缺于 E:45–60（D:775–776、785），lease_expires_at 已画出（D:782 ↔ E:57）；本轮不改 ER。
文字表类型待确认：例如 audit_logs.payload_summary 在 E:95 标 text，而 D:840 只说“摘要”，没有 SQL 类型；这是类型定义未定稿，不属于“ER 多了字段”。

### 9 条候选疑点的复核结论

| 候选 | 复核结论及依据 | 处理 |
| --- | --- | --- |
| 1 | 成立：9 张表，6 个 DDL 起始为 D:711/724/745/764/802/822；三张文字表是 D:838–840，而非 D:836–838。 | 表数已可确定为 9；更正误记，不把表数继续挂为疑问。 |
| 2 | 在两列 status 的 DDL 对比范围内成立：缩写注释在 D:808，D:772 无枚举注释；D:811“非 AC”同源。不是说全章别处都没有 AC（如 D:826）。10 个完整状态名最长为 COMPILE_ERROR/RUNTIME_ERROR，均 13 字符，两列 VARCHAR(20) 均可容纳。 | 已拍板（M1 落地）：2A 使用完整名称并对齐注释，10A 只保存六个逐点终态；见 C。 |
| 3 | 字段缺项成立，具体两侧行号见上文；E:3 的概括性声明不能证明这些字段必然是有意省略。 | 已拍板（M1 落地）：6A 按设计侧差集补齐 ER，本轮不改图。 |
| 4 | 部分成立：§9.3 只有 D:854/856/863 三个明确“唯一”条目；DDL 共 5 个唯一键，另有 tags.name 的文字唯一声明。遗漏为 problems.slug（D:736）、test_cases(problem_id, case_index)（D:756，非 D:757）以及 tags.name（D:838，非 DDL）。 | 已拍板（M1 落地）：11B 将查询索引和唯一约束分栏并列全六项要求；不把 tags.name 误计为已有 DDL。 |
| 5 | 成立：D:838–840 三张表无 DDL，audit_logs.user_id 的可空性未定；E:17 却表达审计恰属 1 个用户。 | 已拍板（M1 落地）：4B/9A 确认非空管理员操作者及物理 FK，5A 确认 M1 严格级阶段补齐三表 DDL；具体字段参数仍待该阶段确认。 |
| 6 | 成立的是设置缺口：D:700/910 要求 UTC；D:717–718 等使用 CURRENT_TIMESTAMP(3)，全文未见 MySQL time_zone 设置。D:652 的 timezone 属 Celery 配置 D:640–653，不能充当 MySQL 设置。 | 已拍板（M1 落地）：3A 采用服务器及所有写入会话 UTC；未执行配置或 SQL。 |
| 7 | 成立于“没有声明”的事实：D:828 仅定义可空列，无对应 FK（D:831–832 只有用户/题目 FK）；E:79 也没有 FK 标记，E:7–17 没有该关系。 | 已拍板（M1 落地）：7A 增加可空引用外键；应用层独立校验同用户、同题目且确为 AC。 |
| 8 | 成立：D:768 注释列 python / cpp，而 D:101/128 将 Python 放前、C++ 放 M3且可砍；注释不等于首版已支持两种语言。 | 已拍板（M1 落地）：1A 首版只允许 python，D:768 注释待同步；不提前落实 C++。 |
| 9 | 成立：D:808 仅写 AC / WA / TLE / ...，未给出明细是否包含 QUEUED/RUNNING/FAILED 的完整集合。 | 已拍板（M1 落地）：2A/10A 明细只用六个完整逐点终态，COMPILE_ERROR 只在提交级，编译失败无明细。 |

## C 约束清单

### 主键

六张 DDL 均以 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4` 结尾（D:711/724/745/764/802/822），存储引擎与字符集一致。

| 表 | 主键 | 设计依据 | ER 依据与待确认 |
| --- | --- | --- | --- |
| users | id | D:712，显式 PRIMARY KEY / NOT NULL / AUTO_INCREMENT | E:19 PK，一致。 |
| problems | id | D:725，同上 | E:26 PK，一致。 |
| test_cases | id | D:746，同上 | E:35 PK，一致。 |
| submissions | id | D:765，同上 | E:46 PK，一致。 |
| submission_cases | id | D:803，同上 | E:62 PK，一致。 |
| user_problem_stats | (user_id, problem_id) | D:823–824 非空、830 联合 PRIMARY KEY，无 AUTO_INCREMENT | E:74–75 联合 PK，一致；不能套用单列自增主键。 |
| tags | id（ER 表达的主键意图） | D:838 只列 id；D:698 有通用主键约定，无该表 DDL | E:82 PK；已拍板（M1 落地）：5A 在严格级设计补齐完整定义，具体字段参数尚待确认。 |
| problem_tags | (problem_id, tag_id) | D:839 明示联合主键，无 DDL | E:86–87 PK；已拍板（M1 落地）：5A 在严格级设计补齐完整定义，具体字段参数尚待确认。 |
| audit_logs | id（ER 表达的主键意图） | D:840 只列 id；D:698 有通用主键约定，无该表 DDL | E:90 PK；已拍板（M1 落地）：5A 在严格级设计补齐完整定义，具体字段参数尚待确认。 |

### 外键及引用动作

“原文”列保留核对基线，不把决定回填为来源事实。原 DDL 显式声明 8 个物理外键；已拍板（M1 落地）：5A/7A/9A/12A 补齐 problem_tags 两个、audit_logs 一个和首次 AC 引用一个，共 12 条待落地外键。除既定两个删除动作外，全部逐条显式 ON DELETE RESTRICT；所有外键逐条显式 ON UPDATE RESTRICT。

| 约束 | 子表列 → 目标列 | 原文 ON DELETE | 原文 ON UPDATE | M1 ON DELETE | M1 ON UPDATE | 出处与结论 |
| --- | --- | --- | --- | --- | --- | --- |
| fk_problems_creator | problems.created_by → users.id | 未写 | 未写 | RESTRICT | RESTRICT | D:738；E:7/32；已拍板（M1 落地）：12A。 |
| fk_cases_problem | test_cases.problem_id → problems.id | 未写 | 未写 | RESTRICT | RESTRICT | D:757；E:10/36；已拍板（M1 落地）：12A。 |
| fk_sub_user | submissions.user_id → users.id | 未写 | 未写 | RESTRICT | RESTRICT | D:796；E:8/47；已拍板（M1 落地）：12A。 |
| fk_sub_problem | submissions.problem_id → problems.id | 未写 | 未写 | RESTRICT | RESTRICT | D:797；E:9/48；已拍板（M1 落地）：12A。 |
| fk_sc_sub | submission_cases.submission_id → submissions.id | CASCADE | 未写 | CASCADE | RESTRICT | D:814；子列非空 D:804；E:11/63；已拍板（M1 落地）：12A。 |
| fk_sc_case | submission_cases.test_case_id → test_cases.id | SET NULL | 未写 | SET NULL | RESTRICT | D:815；子列可空 D:805；E:12/64/102；已拍板（M1 落地）：12A。 |
| fk_ups_user | user_problem_stats.user_id → users.id | 未写 | 未写 | RESTRICT | RESTRICT | D:831；E:13/74；已拍板（M1 落地）：12A。 |
| fk_ups_problem | user_problem_stats.problem_id → problems.id | 未写 | 未写 | RESTRICT | RESTRICT | D:832；E:14/75；已拍板（M1 落地）：12A。 |
| 未命名，文字约定 | problem_tags.problem_id → problems.id（ER 指向） | 未定 | 未定 | RESTRICT | RESTRICT | D:839 说两个外键但无目标子句；E:15/86；已拍板（M1 落地）：5A/12A，约束命名及字段细节待完整 DDL 确认。 |
| 未命名，文字约定 | problem_tags.tag_id → tags.id（ER 指向） | 未定 | 未定 | RESTRICT | RESTRICT | D:839；E:16/87；已拍板（M1 落地）：5A/12A，约束命名及字段细节待完整 DDL 确认。 |
| 仅 ER 标注，未有 DDL | audit_logs.user_id → users.id（ER 指向） | 未定 | 未定 | RESTRICT | RESTRICT | D:840；E:17/91；已拍板（M1 落地）：4B/9A，user_id 非空，仅记录管理员操作。 |
| 新增，名称待 M1 定 | user_problem_stats.first_ac_submission_id → submissions.id | 无此外键 | 无此外键 | RESTRICT | RESTRICT | D:828 原文可空且无 FK；E:79 未标 FK；已拍板（M1 落地）：7A/12A，可空性保持。 |

user_problem_stats.first_ac_submission_id：D:828 与 E:79 的基线仍无该 FK。已拍板（M1 落地）：7A 增加可空外键，数据库层只保证非空引用指向存在的 submissions.id；应用层在设置该引用时独立校验同用户、同题目且 status 为 ACCEPTED，不能把这些业务条件归给单列外键。
已拍板（M1 落地）：12A 在项目设计 §9.1 补“被引用列恒为自增 id、永不更新”的原因说明；该说明不替代每条外键显式声明 ON DELETE / ON UPDATE。本轮只登记，未修改项目设计文档。

### 唯一约束（不把主键重复计数）

| 表/约束名 | 唯一列组 | 定义出处 | §9.3 / ER 对照 |
| --- | --- | --- | --- |
| users / uk_users_username | (username) | D:719，DDL | §9.3 D:854；E:20 UK。 |
| problems / uk_problems_slug | (slug) | D:736，DDL | §9.3 未列；E:27 UK。 |
| test_cases / uk_cases_problem_idx | (problem_id, case_index) | D:756，DDL | §9.3 未列；E:102 明示联合唯一。 |
| submissions / uk_sub_user_idempotency | (user_id, idempotency_key) | D:789，DDL | §9.3 D:856；E:102 明示联合唯一。 |
| submission_cases / uk_sc_sub_idx | (submission_id, case_index) | D:813，DDL | §9.3 D:863；E:102 明示联合唯一。 |
| tags / 未命名 | (name) | D:838，仅文字 | §9.3 原文未列；E:83 UK；已拍板（M1 落地）：5A 补齐 DDL，11B 分栏补全摘要。 |

submissions 的唯一幂等键是 (user_id, idempotency_key) 联合唯一，不能改读成 idempotency_key 单列唯一；D:789、856 与 E:102 三处一致。
原文口径仍为 5 个 DDL 唯一约束 + 1 个文字唯一声明，共 6 个非主键唯一要求；§9.3 明列其中 3 个，缺 2 个 DDL 项和 tags.name 文字项。已拍板（M1 落地）：11B 分栏并补全摘要。
已拍板（M1 落地）：11B 将 §9.3 D:850–864 的查询索引与唯一约束分栏；只改文档/图，不改任何表与约束，无 API 影响。本轮不改设计，不讨论非唯一索引选型。

### 时间与语言的已拍板口径

时间依据：D:700、910 要求 DATETIME(3) 存 UTC；默认/自动更新时间表达式见 D:717–718、734–735、755、788、829。全文出现的 D:652 timezone="UTC" 属 Celery，不能证明 MySQL 会话/服务器时区。
核对基线未写明 MySQL time_zone，不能据此断言实际时间已错。已拍板（M1 落地）：3A 选择服务器及全部写入会话 UTC；以下保留原候选及选择状态，本轮未执行配置或 SQL。

| 候选 | 要确认的约定 | 状态 |
| --- | --- | --- |
| A | 明确 MySQL 服务器及所有写入连接会话采用 UTC，并核对默认时间/自动更新时间表达式与这一约定一致。 | 已拍板（M1 落地）：已选 A，尚未配置或验收。 |
| B | 由应用显式生成 UTC 时间写入，并明确数据库默认值及自动更新时间列是否保留、如何保持一致。 | 本次未选；保留候选供追溯，未改字段定义或业务实现。 |

语言依据：D:768 原注释仍为 python / cpp；D:101、128 为 Python 先行、C++ 放 M3且可砍。已拍板（M1 落地）：1A 首版仅允许 python，D:768 注释待同步为 -- python；本轮不回写设计，也不启用 C++。

### 10 个状态与两列 status 的对应关系

submissions.status 的完整状态来源是 §5.3 D:312–321，列定义为 D:772；submission_cases.status 只有 D:808 的缩写示例及 D:811–812 的输出注释，没有完整明细枚举。
已拍板（M1 落地）：2A/10A 使用下列六个完整逐点终态，编译失败不产生逐点明细；QUEUED、RUNNING、FAILED 与 COMPILE_ERROR 不作为明细状态。E:53、67 及 D:808 仍是未改动的原文，不能把本次决定说成原文已列全。

| 状态（§5.3） | submissions.status | submission_cases.status：已拍板（M1 落地） |
| --- | --- | --- |
| QUEUED | 明确，D:312；D:772 默认值 | 不作为明细状态；只在提交级表示排队。 |
| RUNNING | 明确，D:313 | 不作为明细状态；只在提交级表示执行过程。 |
| ACCEPTED | 明确，D:314 | 使用完整值 ACCEPTED。 |
| WRONG_ANSWER | 明确，D:315 | 使用完整值 WRONG_ANSWER。 |
| COMPILE_ERROR | 明确，D:316 | 不作为明细状态；编译失败无明细行，COMPILE_ERROR 只落 submissions.status。 |
| RUNTIME_ERROR | 明确，D:317 | 使用完整值 RUNTIME_ERROR。 |
| TIME_LIMIT | 明确，D:318 | 使用完整值 TIME_LIMIT。 |
| MEMORY_LIMIT | 明确，D:319 | 使用完整值 MEMORY_LIMIT。 |
| OUTPUT_LIMIT | 明确，D:320 | 使用完整值 OUTPUT_LIMIT。 |
| FAILED | 明确，D:321；error_code 说明见 D:323/773 | 不作为明细状态；只在提交级表示系统失败。 |

10 个提交状态名最大长度为 13，两列 VARCHAR(20) 在长度上足够（D:772、808）。已拍板（M1 落地）：明细仅取上述六个完整逐点终态，不再保留缩写作为存储值。
D:811 与 D:889 仍使用“非 AC”缩写。已拍板（M1 落地）：2A 对齐相关状态及输出保存注释的完整名称，本轮不回写来源。

- 已拍板（M1 落地）：8A 增加 test_cases.updated_at；原文 D:755 仍只有 created_at，R06 与修改接口见 D:1940/1179。本轮接受无法还原旧测试数据的 M1 限制，updated_at 只记录最后改动时点。
- 后端约束：历史 submission_cases 结果保留且不重判（D:846）；不因当前测试数据改变而覆盖历史结果。
- 前端/文本约束：展示与文案不得把当前测试数据称为提交时的原始数据。
- 后续待评估：是否及何时引入测试数据版本化或快照，继续在 open-questions 挂账；本轮未选择版本化方案。

## M1 验收要点

以下是已拍板口径的待实施验收条件，不是本轮已执行或已通过的数据库/API 测试。

- 语言：提交校验只接受 python；cpp 及未知/不支持语言均被拒绝，OpenAPI 枚举与 D:768 待改注释对齐。
- 逐点状态：数据库写入与明细 DTO 只使用 ACCEPTED / WRONG_ANSWER / RUNTIME_ERROR / TIME_LIMIT / MEMORY_LIMIT / OUTPUT_LIMIT 六个完整值，不出现缩写或提交过程/系统状态。
- 编译失败：提交级记录 COMPILE_ERROR，submission_cases 无该次编译失败的明细行；本验收口径不表示首版已启用 C++。
- 审计：user_id 非空，物理外键保证对应 users 记录存在，应用入口校验已登录管理员身份；管理员触发请求仍审计该用户，系统自动动作只进运行日志，不伪造系统用户；未来扩展系统动作审计或用户删号须先改设计并迁移。
- 外键动作：逐条核对 C 节 12 条 M1 外键的目标与显式动作；submission_cases.submission_id 删除级联、test_case_id 删除置空；其余有子行引用的父记录删除受到 RESTRICT 约束，全部被引用列更新动作显式 RESTRICT。核对 §9.1 原因说明存在且不替代逐条声明。
- 首次 AC 引用：数据库外键只负责非空引用对应记录存在；应用层分别拒绝跨用户、跨题目以及非 ACCEPTED 的引用，不能因目标 id 存在就通过业务校验；引用列保持可空。
- 时间：核对 MySQL 服务器及全部写入连接会话的 UTC 约定与时间默认值/自动更新表达式一致。
- 测试数据与历史：允许编辑时更新 updated_at；后端保留历史结果且不重判；前端/文本不得将当前测试数据标成历史原始数据，明确旧数据不可还原的 M1 限制。
