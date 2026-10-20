# GitHub 验收（2026-10-20）

范围：本记录保存文档修订前已推送的 `main` 快照；远端提交与运行状态通过 GitHub API 核对，Mermaid 渲染由用户在 GitHub 文件页逐张截图确认。

## HEAD 与文件树

- 远端 HEAD：[a25f88b](https://github.com/yuliang-1234567/Online-Judge-platform/commit/a25f88be8f1f48768dd9bf02c20d37d12584345b)，完整 SHA 为 `a25f88be8f1f48768dd9bf02c20d37d12584345b`。
- 核验时本地 `main` 的 HEAD 与远端一致；远端 tree 与本地已提交版本的 tree 均为 `fd6985479133f550351ee7455c2f56cc3a34e963`。
- 核对方式：GitHub API `commits/main` 的提交 SHA 与 tree SHA，对照本地 `git rev-parse HEAD`、`git rev-parse 'HEAD^{tree}'`。

## GitHub Actions

截至本次核验共 6 次 run，工作流均为 `Backend checks`。耗时按 GitHub API 的 `created_at` 至 `updated_at` 计算，单位为秒。

| run id | head_sha | status | conclusion | 耗时（秒） | html_url |
| --- | --- | --- | --- | --- | --- |
| [39426220951](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39426220951) | `a25f88be8f1f48768dd9bf02c20d37d12584345b` | `completed` | `success` | 11 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39426220951) |
| [39404777205](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39404777205) | `e11d6731ae3bdfd3c0ef0014abc54b19fafc9701` | `completed` | `success` | 15 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39404777205) |
| [39259410885](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39259410885) | `53e6eb613c0ef258371635624de4dda844606bec` | `completed` | `success` | 15 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39259410885) |
| [39259406493](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39259406493) | `53e6eb613c0ef258371635624de4dda844606bec` | `completed` | `cancelled` | 3 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39259406493) |
| [39257920551](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39257920551) | `bfd88e477f8ad1e1b8a1c17577596fe61d30d789` | `completed` | `success` | 12 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39257920551) |
| [39254739668](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39254739668) | `a9123fedb53088905fb1aa8e2ced4bc665cf2430` | `completed` | `success` | 17 | [查看](https://github.com/yuliang-1234567/Online-Judge-platform/actions/runs/39254739668) |

- 5 次 `success`、1 次 `cancelled`、0 次 `failure`。
- `cancelled` 的那条（39259406493）与同提交的另一条（39259410885）并发，被 `concurrency` 组的 `cancel-in-progress` 取消；为什么一次 push 会触发两条 run 尚未查明，见 [待确认清单](../learning/open-questions.md)。

最近一次运行对应上述 HEAD，耗时 11 秒，结论为 `success`；取消的运行不记作通过。

## Mermaid 文件页渲染

验收来源：用户已在 GitHub 按下列四个文件逐张截图，确认均正常渲染。

| 文件 | GitHub 文件页 | 结果 |
| --- | --- | --- |
| [architecture.md](../figures/architecture.md) | [查看文件](https://github.com/yuliang-1234567/Online-Judge-platform/blob/a25f88be8f1f48768dd9bf02c20d37d12584345b/docs/figures/architecture.md) | 渲染正常 |
| [er.md](../figures/er.md) | [查看文件](https://github.com/yuliang-1234567/Online-Judge-platform/blob/a25f88be8f1f48768dd9bf02c20d37d12584345b/docs/figures/er.md) | 渲染正常 |
| [submission-sequence.md](../figures/submission-sequence.md) | [查看文件](https://github.com/yuliang-1234567/Online-Judge-platform/blob/a25f88be8f1f48768dd9bf02c20d37d12584345b/docs/figures/submission-sequence.md) | 渲染正常 |
| [submission-state.md](../figures/submission-state.md) | [查看文件](https://github.com/yuliang-1234567/Online-Judge-platform/blob/a25f88be8f1f48768dd9bf02c20d37d12584345b/docs/figures/submission-state.md) | 渲染正常 |
