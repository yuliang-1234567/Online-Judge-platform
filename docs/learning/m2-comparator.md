# M2 Comparator（2026-11-13）

目标：按[设计 §7.3.1](../project-design.md#731-输出比对)实现纯字节输出比对。
验收：① 仅忽略 CRLF、指定 ASCII 行尾空白和末尾空行；② 保留其他字节差异；③ 参数化边界测试与默认回归、Ruff/格式检查全绿。

## 做了什么与来源

- 用户本轮明确切换为练习包模式；AI 在既有签名脚手架上起草仓库完整实现、docstring、必要注释、公开接口测试及本记录。
- [实现](../../backend/app/judge/comparator.py)复用同一内部规整函数处理两侧；[测试](../../backend/tests/unit/test_comparator.py)仅调用公开接口，输入全部使用 bytes 字面量，并交换两侧核对对称性。
- 新增 judge 空包标记；没有修改设计、迁移、fixture 或 schema guard，也未提交/推送。
- 用户修改：仓库实现仍为 AI 起草版本；用户已填写私有 01，filled 实测 32/32。答案未回移、不替代仓库源码、不入库。
- 实现与测试按 WSL 原生 Linux 执行；私有路径 local-reference/practice/m2-comparator/ 已被忽略，包外证据在 local-reference/runtime/m2-comparator/。

## 实际检查

以下为实现与生成包时（2026-11-13）的实际检查，命令各从仓库根目录进入 backend 执行，使用已安装依赖，未联网安装；后续 filled 验证与回归见 E1 补记。

| 命令 | 退出码 | 实际结果 |
| --- | --- | --- |
| cd backend && uv run --locked --offline --no-sync ruff check . | 0 | All checks passed |
| cd backend && uv run --locked --offline --no-sync ruff format --check . | 0 | 73 files already formatted |
| cd backend && uv run --locked --offline --no-sync pytest tests/unit/test_comparator.py | 0 | 收集 32，32 passed，0 failed，0.03 s |
| cd backend && uv run --locked --offline --no-sync pytest | 0 | 收集 816，816 passed，0 failed，11.99 s；包含本节 32 项 |

默认 pytest 按 tests/conftest.py 在收集前排除 integration/docker，未开启实库或 Docker 测试入口。
覆盖裸 CR、CRLF、指定行尾空白、空输出、末尾换行/空行、内部空白行/空行、NBSP/VT/FF、BOM、非法 UTF-8、预组/组合字符及行首/行内空白。

## 练习冻结与验收

- 生成时间：2026-11-13T18:42:27+08:00；HEAD：f839d0e61ee54da7856ff2029ea66e559303b176；来源 backend/app/judge/comparator.py，21 行。
- 源 SHA-256：758c70e05071f517fcd51f0de865b998329cb46fd443bf3988214b60a706f775；参考头共 9 行，正文与生成源码逐字节 cmp=0，02 及冻结产物只读。
- 生成时未提交范围：backend/app/judge/__init__.py、backend/app/judge/comparator.py、backend/tests/unit/test_comparator.py；本 learning 在生成后另写，不冒充已包含在 HEAD。
- manifest SHA-256：6036a080f144b7163e935f731bbea9ee1a7197e9536943e4c4fedd6d2a33a5c2；记录 1 个目标、80 个仓库依赖和 5 个包内冻结产物；01 为唯一可填写文件，不参与冻结哈希。
- 完整集合与初始集合均为 1 个函数级节点 tests/unit/test_comparator.py::test_compare_output，各展开 32 项；唯一 TODO 为 compare_output，没有排除项。
- 参考：32/32，通过；pytest/worker/父进程退出码均为 0。
- 初始：0/32，32 failed，符合精确预期红；pytest 退出 1，worker/父进程退出 0 表示初始验收契约通过，不表示用户练习完成。
- 收集集合=固定展开集合，初始失败集合=收集集合；32 项均为私有 01 的 compare_output 抛出精确标记 m2-comparator/compare_output 的 NotImplementedError。
- 新进程按 app.judge.comparator 接入 02/01；模块 __file__、compare_output.co_filename 与测试实际引用均核对正确。网络审计 0 次；dependency_drift=false。
- 生成验收时，包内 manifest 自检、参考只读/正文 SHA 与生成源码一致性通过，01 初始哈希未变化；这些是生成时历史事实。对应 JSON 证据保存在包外 reference.json、initial.json、integrity.json。
- 初始失败节点共用前缀 backend/tests/unit/test_comparator.py::test_compare_output，展开 ID 为：
- identical、empty、crlf、trailing-cr、trailing-ascii、each-line-ascii、no-final-newline、trailing-empty-lines
- empty-vs-crlf、empty-vs-spaces、empty-vs-newlines、empty-vs-ascii、internal-space-line、internal-tab-line、same-utf8、content
- internal-cr-vs-lf、internal-cr-preserved、leading-space、internal-space、internal-tab、internal-empty-line、extra-internal-empty、leading-empty-line
- trailing-nbsp、trailing-vt、trailing-ff、bom、invalid-vs-replacement、unicode-composition、newline-vs-space、nbsp-before-ascii

## E1 filled 验证补记（2026-11-13）

补记日期：2026-11-13（Asia/Taipei）；以下数据来自本聊天上一轮的实际输出，本轮仅补记，未重新运行验证、Ruff 或 pytest。五条命令均经 WSL 在 /home/huyuliang/projects/oj-platform/backend 执行。

| 实际命令 | 退出码 | 实际结果 |
| --- | --- | --- |
| uv run --locked --offline --no-sync python -B ../local-reference/practice/m2-comparator/run_practice.py --verify-only | 0 | contract_passed=true，package_integrity=true，reference_readonly=true，cmp=0，dependency_drift=false，dependency_drift_files=[] |
| uv run --locked --offline --no-sync python -B ../local-reference/practice/m2-comparator/run_practice.py --mode filled | 0 | contract_passed=true，收集 32，32 passed，0 failed |
| uv run --locked --offline --no-sync ruff check . | 0 | All checks passed |
| uv run --locked --offline --no-sync ruff format --check . | 0 | 73 files already formatted |
| uv run --locked --offline --no-sync pytest | 0 | 收集 816，816 passed，0 failed，11.94 s；包含本节 32 项 |

- filled 使用固定完整集合：1 个函数级节点、32 个展开项；failed_nodes=[]、errors=[]、todo_origin={}、network_attempts=0，pytest_exit_code=0、worker_exit_code=0。
- module_file 与 code_file（原 JSON 的 co_filenames.compare_output）均为 /home/huyuliang/projects/oj-platform/local-reference/practice/m2-comparator/01-填空.py；binding_checked=true，实际执行私有填空。
- 上一轮原始 filled JSON 留证于 local-reference/runtime/m2-comparator/filled.json，已忽略；未改运行器、01、02、manifest、测试或仓库实现。
- B1 工作区证据：参考去掉 9 行头后正文与 target 的 SHA-256 均为 758c70e05071f517fcd51f0de865b998329cb46fd443bf3988214b60a706f775，逐字节 cmp=0；提交树匹配待提交前另核。
- 本次全绿仅证明当前目标和测试组合的练习结果；未连接真实 MySQL/Redis/Docker，E2 与 E3 仍待掌握。

## 学习与未验边界

- 我理解了什么：待用户用自己的话补充；本记录中的 AI 解释与检查不能代替用户理解证据。
- 哪里没懂/待补：规整顺序、裸 CR 与空白行边界、字节与 Unicode 区别，仍待用户讲解与理解检查核对，不以练习全绿推断已懂。
- 为什么选当前方案：直接处理 bytes 保留非法编码差异，显式行尾字节集合限制忽略范围，两侧复用同一规则；不使用替换解码、无参 strip 或 splitlines。
- 遇到的坑：跨工具生成脚本首次在 JavaScript 解析阶段因嵌套 Markdown 反引号失败，未执行工程命令、未创建正式包；改用波浪线围栏后一次生成正式包，未改冻结产物或用户答案。
- CI：未核验。本轮未查询远端 CI，当前实现为未提交工作区，没有对应本次源码的远端 CI 证据；本地通过不写成 CI 通过。
- 尚未验证 Worker 接线、Verdict 优先级、输出采集/限额、容器隔离、真实 MySQL/Redis、故障恢复、云上流程或 M2 里程碑；纯函数测试不证明这些成立。
- E1（2026-11-13 补记）：filled 实测 32/32，failed_nodes=[]，errors=[]，成绩与命令见上节；初始模板 0/32 及失败清单保留为生成时历史证据。本项仅记录实测成绩，不宣称个人掌握或 E1 学习验收通过。
- E2：待掌握。原理、代码、修改、调试、验证五项检查及关闭 AI 后独立复现均未完成。
- E3：待掌握。当前 filled 无失败项，原“练习待填”状态已不适用；是否看过参考、独立重写过程仍未核实，不凭代码相似度推断。
- 后续只诊断用户 01 的失败，不代填、不重挖、不迁移答案。代码交付与练习、个人掌握分别记录；提交门及提交树匹配留到用户确认后的提交阶段重新核对。
