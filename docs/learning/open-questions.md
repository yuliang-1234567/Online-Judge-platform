# 待确认清单

| 事项 | 时间/门槛 |
| --- | --- |
| 在途编辑与提交接收的具体事务协调方案 | M1严格级设计，用户确认 |
| 幂等重放顺序 | 11/09—11/11专项复核 |
| lease、续租、接管与围栏 | 11/09—11/11专项复核 |
| 重试门槛与恢复上界 | 11/09—11/11专项复核 |
| 沙箱挂载与目录隔离 | 11/09—11/11专项复核 |
| 榜单重建与并发 | 11/09—11/11专项复核 |
| 补齐 ADR-016 的 V3′ 证据与 build 超时边界（busybox 拉取 6.84 秒；容器直连 PyPI 200 但约 24.17 秒；普通容器直连不等同于 Dockerfile 构建验收） | 06.5 结束时补记，用户确认后再改 ADR |
| [project-design.md](../project-design.md) §19.1 第1737行关于 AI 辅助使用/披露的表述 | 待项目负责人决定是否调整及具体措辞；本轮不改设计 |
| 当前 PAT 含 workflow scope，可修改 .github/workflows/；明文存于本机 ~/.git-credentials（权限 600，仅本仓库生效） | M1 验收后降权为 repo scope，或改用 SSH key 后撤销 |
| GitHub Actions 重复触发原因：同一提交为什么一次 push 会触发两条 run（39259406493、39259410885） | 尚未查明，继续挂账；并发取消结果见 [GitHub 验收记录](../evidence/github-verification.md)。 |

严格级问题不能以时间到期为由跳过；通用问题按准备方案每周回看。

## 已完成

| 事项 | 结果/证据 |
| --- | --- |
| 原生Engine评估、代理网络、Worker环境探针 | 已完成；见 [ADR-016](../adr/ADR-016-wsl-development-environment.md) 和 [06.5 学习记录](06.5-worker-probe.md)。代理每次使用前按 [AGENTS.md](../../AGENTS.md#联网命令的代理取值) 重新取值并探活。 |
| DOCX视觉渲染与Mermaid运行时预览 | 已完成（用户确认）；四张 Mermaid 的 GitHub 文件页验收见 [GitHub 验收记录](../evidence/github-verification.md)。 |
