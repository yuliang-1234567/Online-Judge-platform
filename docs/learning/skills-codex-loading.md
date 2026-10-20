# Codex 项目级 skill 加载验证（2026-10-20）

目标：验证本机 Codex 发现项目级 skill 的位置，并保留仓库内单副本。
验收：探针校验通过；用户新会话实际列出探针；迁移后校验两个现有 skill。实测结论：用户新会话列出 20 个 skill，两个正式 skill 均从项目目录加载，skill-probe 已不在清单里。

## 官方依据

来源：[OpenAI 官方 Build skills 文档](https://learn.chatgpt.com/docs/build-skills)。

> Codex scans .agents/skills in every directory from your current working directory up to the repository root.

| 范围 | 官方列出的路径 |
| --- | --- |
| REPO：当前目录 | `$CWD/.agents/skills` |
| REPO：上级目录 | `$CWD/../.agents/skills` |
| REPO：仓库根 | `$REPO_ROOT/.agents/skills` |
| USER：用户目录 | `$HOME/.agents/skills` |

上述 REPO 路径表示从当前工作目录向上到仓库根的扫描范围。
官方还说明支持 skill 目录的软链接，扫描时会跟随链接目标。

> Codex detects skill changes automatically.

官方补充：如果变更没有出现，重启 Codex；本次验收使用用户新开的项目会话。

## 做了什么：验证方法与结果

- 在项目中创建 `.agents/skills/skill-probe/SKILL.md`，name 为 skill-probe，description 为 probe-UUID。
- 本次 UUID：`2bcac46a-4291-4ef5-97ce-082a2e822426`。
- 使用 `backend/.venv/bin/python` 调用本机 skill-creator 的 quick_validate.py 校验探针目录；输出 `Skill is valid!`，退出码 0。
- 用户在 Codex 中对 oj-platform 新开会话，问“你有哪些 skill”，要求只依据实际加载清单列出名称、description UUID 和来源路径。
- 用户回传结果：新会话共列出 19 个 skill，其中包含 skill-probe；据此确认本机能加载项目的 `.agents/skills`。
- 反证：同一次回答明确说 git-push-workflow、tech-doc-workflow 不在清单里，说明本机该次会话没有扫描仓库根的原位置。
- 本轮按用户指令删除探针并保留 `.agents/skills`，用 git mv 搬入两个现有 skill，更新引用，删除未提交的 codex-skill-sync。

## 我理解了什么

待用户用自己的话补充；本记录不将目录存在或校验通过当作运行时加载证据。

## 遇到的坑与解决、为什么选当前方案

原位置的文件存在，但未进入实际加载清单；改用已被探针验证的项目级目录。
结论：使用 `.agents/skills` 单副本，取消“复制到全局”方案，不再保留同步 skill。

## 哪里没懂 / 待补与未验证边界

其他 IDE 扩展与软链接方式未测；用户已确认迁移后新会话共列出 20 个 skill，其中 git-push-workflow 来源为 `<项目根>/.agents/skills/git-push-workflow/SKILL.md`，tech-doc-workflow 来源为 `<项目根>/.agents/skills/tech-doc-workflow/SKILL.md`，已删除的 skill-probe 不在清单里（19 − 1 + 2 = 20）。

## AI 使用记录

AI 核对官方文档、准备并校验探针；用户亲自开新会话并回传结果。
本轮 AI 在用户明确范围内搬移文件、更新引用与记录，不代替用户验证新会话。
