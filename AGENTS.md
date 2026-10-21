# OJ 仓库协作规则

## 阅读与依据

- 开始工作前读本文件、`docs/ai-workflow.md` 及当前任务涉及的设计章节。
- **skill 触发条件（满足即读，读完必须按其执行）**：
  | 触发动作 | 必读文件 |
  |---|---|
  | 任何 Git 暂存、提交、推送、标签操作 | `.agents/skills/git-push-workflow/SKILL.md` |
  | 在 `docs/` 下写或改文档、模块文档、学习笔记 | `.agents/skills/tech-doc-workflow/SKILL.md` |
  | 每轮工作（开始审要求、结尾列风险） | `.agents/skills/risk-checkpoint/SKILL.md` |
- **规则优先级**：用户当前明确指令 > 本文件 > skill 文件 > 其他说明文档。冲突时停下报告，不自行取舍。
- `docs/project-design.md` 是“做什么”的唯一依据；`docs/development-workflow.md` 是通用协作准备方案，`docs/ai-workflow.md` 记录 OJ 已确认的协作约定。
- 当前用户明确指令优先于历史阶段说明。发现设计、代码或 OpenAPI 不一致，先停下报告，由用户决定，不默改设计或文档。
- 工程命令在 WSL 的 Linux 文件系统和原生 Linux 进程中执行；不通过 Windows UNC 路径操作 WSL 工程，不在 `/mnt/d` 下开发。

## 权限与环境变更

- **每次需要 root 的操作，必须先说明原因、列出将执行的完整具体命令，等待用户明确同意后再执行。** 说明固定为三段：目的（含完整具体命令）、影响面、回滚。这包括 `sudo`、`su`、`wsl.exe --user root` / `-u root` 等入口；不得遇到 sudo 密码提示后自行换 root 入口。
- **修改 sudoers 同样必须逐次说明原因和具体命令，并获得用户明确同意。** sudo 缓存、技术上可执行或过去的一次批准，都不代表本次已获批准。
- 2026-10-19 的 Docker 安装获用户单次认可，不构成后续 root 操作授权。系统配置变更及验证结果记入 `docs/learning/00-wsl-environment.md`。
- 当前网络诊断只读；代理、DNS、镜像源的变更先给方案，由用户选择。不自行修改，不使用来源不明的镜像站。
- 不要求用户在聊天中提供 sudo 密码、访问令牌或真实密钥。

## 联网命令的代理取值

- 不要从任何文档里抄代理端口，包括 `local-reference/` 下的诊断记录；那些是历史快照，不代表当前值。
- 需要用代理时，按以下顺序取值：
  1. 读取 Windows 系统代理设置。WSL 的 PATH 里没有 `powershell.exe`，必须使用绝对路径；将输出捕获到当前进程变量，不打印完整代理地址：

     ```bash
     P="$(/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile \
       -Command "(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings').ProxyServer")"
     P="${P%$'\r'}"
     ```

  2. 对本次命令真正要访问的域名探活，不统一使用 GitHub：

     | 用途 | 探活命令 | HTTP 判据 |
     | --- | --- | --- |
     | git | `curl -sS -o /dev/null -w '%{http_code}\n' --proxy "http://$P" --max-time 10 https://github.com/` | `200` |
     | uv / pip | `curl -sS -o /dev/null -w '%{http_code}\n' --proxy "http://$P" --max-time 10 https://pypi.org/pypi/fastapi/json` | `200`；小体积 JSON，避免索引页传输被超时截断造成误判 |
     | docker | `curl -sS -o /dev/null -w '%{http_code}\n' --proxy "http://$P" --max-time 10 https://registry-1.docker.io/v2/` | `401`，认证入口正常响应即为可达 |

  3. 探活必须在真正执行联网命令的同一次操作中完成，不提前测好后假设一直有效；直连是否可用也每次实测，不在文档里断言“必须走代理”。
  4. 探活失败就停下报告；不要换端口重试，也不要从历史文档里找备选值。
- 端口只在本机使用，不写进仓库任何文件；命令里也不要打印完整代理地址。

## 小节协作与理解

- 先讲解，再写代码；方案确认后才动手，不一次提供整份代码。每个小节先给“一句话目标 + 三条验收标准”，等用户说开始；用户明确批准直接开始时，可按批准范围执行。
- 严格级：认证、权限、事务、数据库设计、状态机 claim/finalize/lease 及核心业务规则。先解释思路和取舍，核心逻辑由用户写，AI 审查并补测试；五项理解检查和关闭 AI 后复现不能跳过。
- 标准/宽松级：普通接口、查询、配置、脚手架，可由 AI 在批准范围内实现并解释。疑问记入 `docs/learning/open-questions.md`，按准备方案定期复查。
- 完成小节后实际运行 Ruff 和 pytest，如实报告命令与结果。纯文档/配置阶段若工具未安装、工程或测试尚不存在，明确写未运行及原因，执行适用的文件、忽略规则和 diff 检查；不把它称为测试通过。
- 学习记录写明 AI 生成部分、用户修改及未理解的问题；不得编造功能、CI、测试或性能数据。
- 进度不足只削减范围，不跳过严格级理解与正确性检查。五类 W5 专项设计按已批准计划复核，不提前修改。

## 阶段 06 当前顺序与边界

- 06.1：`.gitignore`、`.gitattributes`、`deploy/.env.example`、本文件及环境学习记录。该小节提交前不开始其他工程小节。
- 06.2：backend 骨架、uv/锁文件、Ruff、pytest、`/healthz` 与测试；先给目标和验收，获准开始后先验证官方 PyPI 的索引与依赖下载可达。
- 06.3：仅 MySQL、Redis 的开发 Compose 与 Makefile（已完成，宿主端口 13306／16379）。
- 06.4：pre-commit、最小 CI、README（已完成，见 README 进度表）。
- 06.5：Worker 环境探针（已完成，见 README 进度表），限时半天；通过与否均记录 ADR-016 与 learning。API 在 WSL 本地运行，阶段 06 不做 API 容器化。
- Node 暂不安装；首次推送已完成，四张 Mermaid 图已在 GitHub 文件页逐张截图确认渲染正常，验收结果见 [GitHub 验收记录](docs/evidence/github-verification.md)。

## Git 与公开仓库

- 每个小节提交前先展示包含新文件的 diff 摘要和验证结果，等待用户确认后才提交；只按明确路径暂存，不用 `git add .`、`git add -A`、`git add -u`、任何 force 或 no-verify，不改写已推送历史。
- 提交与推送按小节切分：提交不跨小节，推送只推一个小节，不跨小节攒批次；同一小节内的提交拆分（主本一个、记录一个，先主本后记录）与同一次推送的要求，按 `.agents/skills/git-push-workflow/SKILL.md` 第四节执行。
- 中文提交信息写入 UTF-8 临时文件，以 `git commit -F` 传入，不追加署名行。
- 首次推送在 06.4 之后；先列全部将入库文件供用户审阅。每次推送都重新读取实际远程 URL 与分支并请用户确认位置；不把 skill 中的预期地址视作授权。远程 origin 已添加；每次推送仍须按 skill 第二节单独确认位置。
- Word 原件、求职规划、真实 `.env`、凭据、真实隐藏测试数据、数据库备份和判题产物不入库；`local-reference/` 只保留私有材料。测试用 fixtures 可入库。
- 根目录与子目录只保留一份环境模板：`deploy/.env.example`。真实配置使用 `deploy/.env`，不得提交。

## 工作区形态

本项目可能以两种形态打开：WSL 内部路径，或 Windows 的 UNC 路径
（\\wsl.localhost\Ubuntu\...）。无论哪种，执行规则相同：

- 一切命令通过 wsl.exe -d Ubuntu --cd <项目绝对路径> --exec <命令> 执行
- 禁止用 PowerShell 的 Set-Content / New-Item / Remove-Item 直接写项目目录，
  属主、权限位、换行会被破坏
- git 命令同样在 Linux 侧执行，不要在 Windows 侧对仓库运行 git
