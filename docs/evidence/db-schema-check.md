# 数据库表与 ER 核对（2026-10-21）

基线：本地提交 bb8f0c3。D = [project-design.md](../project-design.md)，E = [er.md](../figures/er.md)；下文 D/E 后的数字均为这两个文件的一基行号。
范围：已读 D:686–913、304–326、1867–1884 与 E:1–104，并核对全文时间设置及语言范围。只记录现状与待确认项；未修改来源、未写迁移、未建表、未执行 SQL。
裁定口径：文本或约束已能互相印证记“一致”；缺少定义、必选性或展示意图无法确认记“转待确认”，不将疑问自动改成设计决定。

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
| users | D:711–720 | E:18–24 | 一致；时间字段差集见下表。 |
| problems | D:724–739 | E:25–33 | 一致；difficulty 等是否应展示转待确认。 |
| test_cases | D:745–758 | E:34–44 | 一致；创建时间差集见下表。 |
| submissions | D:764–798 | E:45–60、102 | 一致；联合唯一键有文字说明，统计/排队字段展示范围转待确认。 |
| submission_cases | D:802–816 | E:61–72、102 | 一致；字段名齐全，status 取值仍转待确认。 |
| user_problem_stats | D:822–833 | E:73–80、102 | 一致；联合主键和两个 FK 对应，更新时间未展示。 |
| tags | D:838 | E:81–84、104 | 转待确认；字段名和 name 唯一相符，但无完整 DDL，类型及主键细节未定稿。 |
| problem_tags | D:839 | E:85–88、104 | 转待确认；联合主键和两个外键意图相符，完整约束声明缺失。 |
| audit_logs | D:840 | E:89–99、104 | 转待确认；字段名相符，但 user_id 可空性、物理 FK 和类型等无完整定义。 |

### 11 条关系

| # | 关系及 ER 基数 | 设计侧依据 | ER 侧行号 | 裁定 |
| --- | --- | --- | --- | --- |
| 1 | users → problems：每题恰属 1 个创建人，用户可创建 0 至多题 | created_by 非空 D:733；FK D:738 | E:7、32 | 一致 |
| 2 | users → submissions：每次提交恰属 1 个用户，用户可有 0 至多次提交 | user_id 非空 D:766；FK D:796 | E:8、47 | 一致 |
| 3 | problems → submissions：每次提交恰属 1 题，题目可有 0 至多次提交 | problem_id 非空 D:767；FK D:797 | E:9、48 | 一致 |
| 4 | problems → test_cases：每测试点恰属 1 题，题目可有 0 至多测试点 | problem_id 非空 D:747；FK D:757 | E:10、36 | 一致 |
| 5 | submissions → submission_cases：每条明细恰属 1 次提交，提交可有 0 至多明细 | submission_id 非空 D:804；FK/级联删除 D:814 | E:11、63 | 一致 |
| 6 | test_cases → submission_cases：明细可对应 0 或 1 个测试点，测试点可被 0 至多明细引用 | test_case_id 可空 D:805；删除置空 D:815、846 | E:12、64、102 | 一致 |
| 7 | users → user_problem_stats：统计行恰属 1 个用户，用户可有 0 至多统计行 | 非空 D:823；联合 PK D:830；FK D:831 | E:13、74、102 | 一致 |
| 8 | problems → user_problem_stats：统计行恰属 1 题，题目可有 0 至多统计行 | 非空 D:824；联合 PK D:830；FK D:832 | E:14、75、102 | 一致 |
| 9 | problems → problem_tags：关联行恰属 1 题，题目可有 0 至多关联行 | D:839 写联合主键及两个外键，未给完整定义 | E:15、86 | 转待确认；关联意图一致，目标列/动作等待 DDL 定稿。 |
| 10 | tags → problem_tags：关联行恰属 1 标签，标签可有 0 至多关联行 | D:839 写联合主键及两个外键，未给完整定义 | E:16、87 | 转待确认；关联意图一致，目标列/动作等待 DDL 定稿。 |
| 11 | users → audit_logs：每条审计恰属 1 用户，用户可有 0 至多审计 | D:840 仅列 user_id，未说明可空性及物理 FK | E:17、91 | 转待确认；不能由 ER 的必选关系反推文字表已规定 NOT NULL。 |

### 每张表的三类字段差集

E:3 仅声明“只展示核心字段，完整结构以设计第 9 章为准”，未逐字段说明省略意图。因此只在有具体依据时判为“有意省略”；本次不能把所有缺项自动归入该类。下表完整列出设计有而 ER 无的字段，展示意图保持待确认。
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

展示范围待确认：problems.difficulty 缺于 E:25–33（D:729）；submissions.passed_cases、total_cases、queued_at 缺于 E:45–60（D:775–776、785），但 lease_expires_at 已画出（D:782 ↔ E:57）。是否补画核心统计/排队字段，交 M1 确认，本记录不改图。
文字表类型待确认：例如 audit_logs.payload_summary 在 E:95 标 text，而 D:840 只说“摘要”，没有 SQL 类型；这是类型定义未定稿，不属于“ER 多了字段”。

### 9 条候选疑点的复核结论

| 候选 | 复核结论及依据 | 处理 |
| --- | --- | --- |
| 1 | 成立：9 张表，6 个 DDL 起始为 D:711/724/745/764/802/822；三张文字表是 D:838–840，而非 D:836–838。 | 表数已可确定为 9；更正误记，不把表数继续挂为疑问。 |
| 2 | 在两列 status 的 DDL 对比范围内成立：缩写注释在 D:808，D:772 无枚举注释；D:811“非 AC”同源。不是说全章别处都没有 AC（如 D:826）。10 个完整状态名最长为 COMPILE_ERROR/RUNTIME_ERROR，均 13 字符，两列 VARCHAR(20) 均可容纳。 | 缩写与正式值的映射转待确认，详见 C；不据缩写注释直接替换枚举。 |
| 3 | 字段缺项成立，具体两侧行号见上文；E:3 的概括性声明不能证明这些字段必然是有意省略。 | 是否补画 difficulty、通过统计与 queued_at 转待确认。 |
| 4 | 部分成立：§9.3 只有 D:854/856/863 三个明确“唯一”条目；DDL 共 5 个唯一键，另有 tags.name 的文字唯一声明。遗漏为 problems.slug（D:736）、test_cases(problem_id, case_index)（D:756，非 D:757）以及 tags.name（D:838，非 DDL）。 | 推翻“tags.name 也是 DDL 唯一键”的混计；唯一约束摘要补全与分栏建议见 C，转待确认。 |
| 5 | 成立：D:838–840 三张表无 DDL，audit_logs.user_id 的可空性未定；E:17 却表达审计恰属 1 个用户。 | 三张表完整定义及审计关系必选性转待 M1 确认。 |
| 6 | 成立的是设置缺口：D:700/910 要求 UTC；D:717–718 等使用 CURRENT_TIMESTAMP(3)，全文未见 MySQL time_zone 设置。D:652 的 timezone 属 Celery 配置 D:640–653，不能充当 MySQL 设置。 | 不断言现有时间已错；C 列两个候选方案，只列不选。 |
| 7 | 成立于“没有声明”的事实：D:828 仅定义可空列，无对应 FK（D:831–832 只有用户/题目 FK）；E:79 也没有 FK 标记，E:7–17 没有该关系。 | 不将字段名当成外键；是否需要新增约束交 M1 确认。 |
| 8 | 成立：D:768 注释列 python / cpp，而 D:101/128 将 Python 放前、C++ 放 M3且可砍；注释不等于首版已支持两种语言。 | 首版 submissions.language 允许值待 M1 定，不提前落实 C++。 |
| 9 | 成立：D:808 仅写 AC / WA / TLE / ...，未给出明细是否包含 QUEUED/RUNNING/FAILED 的完整集合。 | 两列 status 不能混用已确定与未确定范围；对应矩阵见 C。 |

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
| tags | id（ER 表达的主键意图） | D:838 只列 id；D:698 有通用主键约定，无该表 DDL | E:82 PK；类型/自增等具体声明转待 M1 确认。 |
| problem_tags | (problem_id, tag_id) | D:839 明示联合主键，无 DDL | E:86–87 PK；完整定义转待 M1 确认。 |
| audit_logs | id（ER 表达的主键意图） | D:840 只列 id；D:698 有通用主键约定，无该表 DDL | E:90 PK；类型/自增等具体声明转待 M1 确认。 |

### 外键及引用动作

“未写”表示来源没有显式子句；不擅自补成 CASCADE、SET NULL 或其他动作。DDL 显式声明 8 个物理外键；另列两个文字外键意图，以及一个仅 ER 标注的审计外键待确认。

| 约束 | 子表列 → 目标列 | ON DELETE | ON UPDATE | 出处与结论 |
| --- | --- | --- | --- | --- |
| fk_problems_creator | problems.created_by → users.id | 未写 | 未写 | D:738；E:7/32，一致。 |
| fk_cases_problem | test_cases.problem_id → problems.id | 未写 | 未写 | D:757；E:10/36，一致。 |
| fk_sub_user | submissions.user_id → users.id | 未写 | 未写 | D:796；E:8/47，一致。 |
| fk_sub_problem | submissions.problem_id → problems.id | 未写 | 未写 | D:797；E:9/48，一致。 |
| fk_sc_sub | submission_cases.submission_id → submissions.id | CASCADE | 未写 | D:814；子列非空 D:804；E:11/63，一致。 |
| fk_sc_case | submission_cases.test_case_id → test_cases.id | SET NULL | 未写 | D:815；子列可空 D:805；E:12/64/102，一致。 |
| fk_ups_user | user_problem_stats.user_id → users.id | 未写 | 未写 | D:831；E:13/74，一致。 |
| fk_ups_problem | user_problem_stats.problem_id → problems.id | 未写 | 未写 | D:832；E:14/75，一致。 |
| 未命名，文字约定 | problem_tags.problem_id → problems.id（ER 指向） | 未定 | 未定 | D:839 说两个外键但无目标子句；E:15/86；转待确认。 |
| 未命名，文字约定 | problem_tags.tag_id → tags.id（ER 指向） | 未定 | 未定 | D:839；E:16/87；转待确认。 |
| 仅 ER 标注，未有 DDL | audit_logs.user_id → users.id（ER 指向） | 未定 | 未定 | D:840 未声明物理 FK/可空性；E:17/91；转待确认。 |

user_problem_stats.first_ac_submission_id：D:828 无物理外键，E:79 未标 FK；不计入上述 8 个已声明外键，也不凭字段名新增到关系清单。是否约束该引用待 M1 确认。

### 唯一约束（不把主键重复计数）

| 表/约束名 | 唯一列组 | 定义出处 | §9.3 / ER 对照 |
| --- | --- | --- | --- |
| users / uk_users_username | (username) | D:719，DDL | §9.3 D:854；E:20 UK。 |
| problems / uk_problems_slug | (slug) | D:736，DDL | §9.3 未列；E:27 UK。 |
| test_cases / uk_cases_problem_idx | (problem_id, case_index) | D:756，DDL | §9.3 未列；E:102 明示联合唯一。 |
| submissions / uk_sub_user_idempotency | (user_id, idempotency_key) | D:789，DDL | §9.3 D:856；E:102 明示联合唯一。 |
| submission_cases / uk_sc_sub_idx | (submission_id, case_index) | D:813，DDL | §9.3 D:863；E:102 明示联合唯一。 |
| tags / 未命名 | (name) | D:838，仅文字 | §9.3 未列；E:83 UK；完整 DDL 转待确认。 |

submissions 的唯一幂等键是 (user_id, idempotency_key) 联合唯一，不能改读成 idempotency_key 单列唯一；D:789、856 与 E:102 三处一致。
口径：5 个 DDL 唯一约束 + 1 个文字唯一声明，共 6 个非主键唯一要求；§9.3 明列其中 3 个，缺 2 个 DDL 项和 tags.name 文字项，摘要是否补齐转待确认。
口径意见（未采纳、未改设计）：§9.3 D:850–864 同时列“服务查询的索引”和“保证唯一的约束”，建议以后分成两栏；本次不讨论非唯一索引选型。

### 时间与语言的待确认边界

时间依据：D:700、910 要求 DATETIME(3) 存 UTC；默认/自动更新时间表达式见 D:717–718、734–735、755、788、829。全文出现的 D:652 timezone="UTC" 属 Celery，不能证明 MySQL 会话/服务器时区。
当前缺少 MySQL time_zone 的明确约定，不能单凭 CURRENT_TIMESTAMP(3) 就认定 UTC 要求已满足，也不能断言必然已经写入非 UTC 数据。以下两个候选方案仅列出，均未选择或执行：

| 候选 | 要确认的约定 | 状态 |
| --- | --- | --- |
| A | 明确 MySQL 服务器及所有写入连接会话采用 UTC，并核对默认时间/自动更新时间表达式与这一约定一致。 | 待确认；不执行配置或 SQL。 |
| B | 由应用显式生成 UTC 时间写入，并明确数据库默认值及自动更新时间列是否保留、如何保持一致。 | 待确认；不改字段定义或业务实现。 |

语言依据：D:768 为 python / cpp 注释；D:101、128 为 Python 先行、C++ 放 M3且可砍。首版允许值待 M1 定，不能将注释当成已完成的 C++ 支持。

### 10 个状态与两列 status 的对应关系

submissions.status 的完整状态来源是 §5.3 D:312–321，列定义为 D:772；submission_cases.status 只有 D:808 的缩写示例及 D:811–812 的输出注释，没有完整明细枚举。
“概念可对应”不代表已选定存储拼写；“待确认”也不代表该状态被禁止。E:53、67 只标 varchar，不能补出枚举。

| 状态（§5.3） | submissions.status | submission_cases.status |
| --- | --- | --- |
| QUEUED | 明确，D:312；D:772 默认值 | 待确认：D:808 未说明是否为明细状态。 |
| RUNNING | 明确，D:313 | 待确认：D:808 未说明是否为明细状态。 |
| ACCEPTED | 明确，D:314 | AC / “非 AC”提供概念对应（D:808/811）；完整存储值待确认。 |
| WRONG_ANSWER | 明确，D:315 | WA 提供概念对应（D:808）；完整存储值待确认。 |
| COMPILE_ERROR | 明确，D:316 | D:808 的省略号没有列明；是否存在明细记录/状态待确认。 |
| RUNTIME_ERROR | 明确，D:317 | D:812 涉及运行时错误输出，但未定义 status 值；转待确认。 |
| TIME_LIMIT | 明确，D:318 | TLE 提供概念对应（D:808）；完整存储值待确认。 |
| MEMORY_LIMIT | 明确，D:319 | D:808 未列完整值；转待确认。 |
| OUTPUT_LIMIT | 明确，D:320 | D:808 未列完整值；转待确认。 |
| FAILED | 明确，D:321；error_code 说明见 D:323/773 | 待确认：D:808 未说明系统失败是否为明细状态。 |

10 个完整状态名的最大长度是 13（COMPILE_ERROR、RUNTIME_ERROR），两列 VARCHAR(20) 在长度上足够（D:772、808）；长度足够不能解决枚举范围及缩写映射问题。
D:811 的 stdout_snippet“仅非 AC 的样例点”与 D:889 输出保存规则使用同源缩写；是否统一注释措辞转待确认，不在本次改写。

- 待确认：test_cases 有 created_at（D:755），没有 updated_at；而 R06 允许在无在途提交时修改测试点（D:1940；修改接口见 D:1179，历史不重判见 D:846）。一旦修改，历史 submission_cases 已写入的结果与当前测试数据不再对应，也没有时间戳可判断改动时点。是否增加 updated_at 或改用其他一致性手段，留 M1 定。
