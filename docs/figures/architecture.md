# OJ总体架构

Mermaid是本图唯一维护源；[v1.1原PNG](reference/architecture-v1.1.png)仅作存档。这里只修正任务来源、Beat调度和Docker访问箭头，不变更W5待复核策略。

```mermaid
flowchart TB
    Browser["浏览器 Vue3 / TypeScript / Monaco"] --> Nginx["Nginx HTTPS / 反向代理"]
    Nginx --> API["FastAPI async / 认证与业务API"]
    API -->|"读写 / 事务"| MySQL["MySQL 事实数据"]
    API -->|"入队 / 缓存 / 限流 / 榜单"| Redis["Redis db0 broker / db1其余"]
    JudgeWorker["可信 Judge Worker / 同步 prefork"] -->|"从judge队列取任务"| Redis
    JudgeWorker -->|"claim / lease / finalize"| MySQL
    Beat["单实例 Celery Beat"] -->|"投递维护任务"| Redis
    MaintWorker["可信 Maintenance Worker"] -->|"从maintenance队列取任务"| Redis
    MaintWorker -->|"补偿 / 恢复 / 榜单重建"| MySQL
    JudgeWorker -->|"run / wait / remove"| Daemon["Docker daemon"]
    MaintWorker -->|"清理孤儿容器"| Daemon
    Daemon -->|"创建与管理"| Judge["不可信判题容器 / 每测试点一次性容器"]
    Judge -->|"退出信息与输出由Worker读取"| JudgeWorker
```

用户容器无Docker socket，期望输出仅留在Worker侧。阶段06开发时API在本地运行，Compose仅起MySQL与Redis；本图描述目标逻辑架构。
