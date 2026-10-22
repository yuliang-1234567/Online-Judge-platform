# 核心表关系

Mermaid是本图唯一维护源；[v1.1原PNG](reference/er-v1.1.png)仅作存档。修正test_cases的input_size/output_size，与已批准的限制快照及追踪/幂等字段同步。字段按设计第9章已确认定义同步，类型细节、可空性与约束以设计主本为准。

```mermaid
erDiagram
    users ||--o{ problems : creates
    users ||--o{ submissions : submits
    problems ||--o{ submissions : receives
    problems ||--o{ test_cases : contains
    submissions ||--o{ submission_cases : records
    test_cases o|--o{ submission_cases : references
    users ||--o{ user_problem_stats : has
    problems ||--o{ user_problem_stats : has
    problems ||--o{ problem_tags : has
    tags ||--o{ problem_tags : labels
    users ||--o{ audit_logs : operates
    submissions |o--o| user_problem_stats : first_ac_reference
    users {
        bigint id PK
        varchar username UK
        varchar password_hash
        varchar role
        varchar status
        datetime created_at
        datetime updated_at
    }
    problems {
        bigint id PK
        varchar slug UK
        varchar title
        mediumtext description
        varchar difficulty
        int time_limit_ms
        int memory_limit_mb
        varchar status
        bigint created_by FK
        datetime created_at
        datetime updated_at
    }
    test_cases {
        bigint id PK
        bigint problem_id FK
        int case_index
        tinyint is_sample
        mediumtext input_data
        mediumtext expected_output
        int input_size
        int output_size
        char sha256
        datetime created_at
        datetime updated_at
    }
    submissions {
        bigint id PK
        bigint user_id FK
        bigint problem_id FK
        varchar language
        text code
        int time_limit_ms_snapshot
        int memory_limit_mb_snapshot
        varchar status
        varchar error_code
        varchar error_message
        smallint passed_cases
        smallint total_cases
        int runtime_ms
        int memory_kb
        tinyint attempts
        tinyint enqueue_count
        varchar worker_id
        datetime lease_expires_at
        varchar request_id
        varchar idempotency_key
        datetime queued_at
        datetime started_at
        datetime finished_at
        datetime created_at
    }
    submission_cases {
        bigint id PK
        bigint submission_id FK
        bigint test_case_id FK
        int case_index
        tinyint is_sample
        varchar status
        int runtime_ms
        int memory_kb
        varchar stdout_snippet
        varchar stderr_snippet
    }
    user_problem_stats {
        bigint user_id PK, FK
        bigint problem_id PK, FK
        int attempts
        tinyint solved
        datetime first_ac_at
        bigint first_ac_submission_id FK
        datetime updated_at
    }
    tags {
        bigint id PK
        varchar name UK
        datetime created_at
    }
    problem_tags {
        bigint problem_id PK, FK
        bigint tag_id PK, FK
    }
    audit_logs {
        bigint id PK
        bigint user_id FK
        varchar action
        varchar resource_type
        bigint resource_id
        varchar payload_summary
        varchar request_id
        varchar ip
        datetime created_at
    }
```

submissions的唯一幂等约束是(user_id, idempotency_key)，不是idempotency_key单列唯一。test_cases唯一约束是(problem_id, case_index)，submission_cases是(submission_id, case_index)。test_case_id在删除测试点后可空，用户/题目统计以联合主键计数。

图中类型细节、可空性、默认值与引用动作以设计第9章为准；三张文字表的完整 DDL 已于 M1 确认并写入设计 §9.2.4。audit_logs.user_id 为非空管理员引用；first_ac_submission_id 可空，其同用户、同题目及 ACCEPTED 条件由应用层校验。事务锁定方案不在本次修改范围。
