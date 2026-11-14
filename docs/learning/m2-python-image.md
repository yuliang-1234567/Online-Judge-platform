# M2.2 Python 判题镜像与语言配置（2026-11-14）

目标：交付来源与版本可追溯的 Python 镜像、内部语言配置和可信冒烟。
验收：① 固定真实基础 digest 并记录工具/镜像身份；② 精确语言白名单与不可变配置通过单测；③ 真实冒烟及仓库检查分别通过。
编号依据：用户于 2026-11-14 确认 12 段施工划分，本节为 M2.2；不修改设计主本。
开始基线：main / d5f9590826c17dbe2b00237036b91b985dc1104f；本节未暂存、提交或推送。

## 做了什么与内部边界

- AI 起草[镜像及忽略规则](../../judge-images/python/Dockerfile)、[语言表](../../backend/app/judge/languages.py)、[语言单测](../../backend/tests/unit/test_languages.py)、[冒烟测试](../../backend/tests/docker/test_python_judge_image.py)和本记录；用户批准方案，本节无用户源码修改。
- 对照设计 §6.5/§16：languages 是内部配置表，镜像放 judge-images/python；不变更 HTTP/OpenAPI，不复制旧探针逻辑作为生产 Runner。
- LanguageSpec 为冻结 dataclass，字段值只含 str/tuple/None；get_language 仅接受精确 python，大小写/前后空白及不支持语言均抛 ValueError，不读环境、不调用 Docker/数据库、不拼 shell。
- 保留既有 JUDGE_IMAGE_PYTHON=oj-judge-python:1，不修改 deploy/.env.example 或 Settings；实际配置读取和本地镜像 ID 核验留 M2.3。
- 镜像仅装 Python 标准库与 GNU 工具；默认 USER 65532:65532、WORKDIR /work、无固定 ENTRYPOINT，CMD 仅显示 Python 版本。
- 构建上下文仅 judge-images/python，.dockerignore 默认全排除，只放行 Dockerfile 和 .dockerignore；不发送真实配置、用户代码或测试数据。
- 65532 只是镜像默认值；设计 §7.2 的宿主专用同 UID/GID、最小挂载、输出容量/inode 配额仍待 M2.3 核验，不以本节结果宣称生产隔离就绪。

## 构建与实际身份

从官方标签实时查询基础 digest 后固定到 Dockerfile，未复用旧 python:3.12-slim 缓存的 digest。基础与最终镜像身份：

| 项目 | 实测值 |
| --- | --- |
| 基础标签 | docker.io/library/python:3.12-slim-bookworm |
| 固定基础 digest | sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df |
| 最终标签 | oj-judge-python:1 |
| 最终镜像 ID | sha256:d9d207bdefaced6e35ce8b8fea9d004156dd24d67bd0c3764a9d407af89136be |
| 构建/运行平台 | linux/amd64 |
| Python 实际版本与身份 | 3.12.16；容器 UID/GID=65532:65532 |
| coreutils / timeout | Debian 包 9.1-1；timeout 自报 GNU coreutils 9.1 |
| time | Debian 包 1.9-0.2；二进制自报 time (GNU Time) UNKNOWN，未伪写成自报 1.9 |

- 实际构建命令（仓库根）：docker build --pull=false --progress=plain --iidfile local-reference/runtime/m2-python-image/image.id -t oj-judge-python:1 judge-images/python，退出 0；此前该目标标签不存在。
- 当次 registry 探活通过当前系统代理返回 401，官方 Debian bookworm/security 源直连探活返回 200；随后实际构建成功。仅在进程内使用代理，不记录端点、不改代理/DNS/镜像源。
- coreutils/time 经官方 Debian 源在同一构建步骤更新索引、安装并清理索引；包写入镜像层，未使用宿主 root 入口或修改宿主软件包。
- digest 固定基础层；apt 包来自当次官方仓库，因此承诺来源/版本/镜像 ID 可追溯，不承诺重复构建逐字节相同。
- 保留构建镜像供后续小节使用；没有清理其他镜像、修改旧探针或运行用户提交。

## 实际检查

均经 WSL 执行；下表命令的目录为 backend，uv 使用 --locked --offline --no-sync，不安装后端依赖。

| 命令 | 退出码 | 实际结果 |
| --- | --- | --- |
| uv run --locked --offline --no-sync ruff check . | 0 | All checks passed |
| uv run --locked --offline --no-sync ruff format --check . | 0 | 76 files already formatted |
| uv run --locked --offline --no-sync pytest tests/unit/test_languages.py | 0 | 收集 11，11 passed，0 failed，0.02 s |
| uv run --locked --offline --no-sync pytest | 0 | 收集 827，827 passed，0 failed，11.31 s |
| uv run --locked --offline --no-sync pytest -o addopts="-ra --strict-markers" -m docker -s tests/docker/test_python_judge_image.py | 0 | 收集 9，9 passed，0 failed，4.67 s |

- 首次 lint/format 发现新冒烟文件的行长/排版问题；只格式化该新文件后复查通过，未改断言、旧测试或 M2.1。
- 默认 pytest 由既有 conftest 在收集前排除 integration/docker；827 包含新增语言测试 11 项，未连接 MySQL/Redis。Docker 冒烟另行显式运行，保留严格 marker 检查。
- 冒烟只执行固定可信脚本：默认 CMD、版本/身份、stdin/stdout/stderr、主动退出 23、GNU 工具版本、time 数值格式、timeout 终止可信等待及包版本。
- 每次使用已确认本地镜像 ID，显式 create→核验→start→wait/inspect；禁网、禁止拉取、只读根、无宿主挂载，资源有界。真实退出码由 wait 与 inspect 共同确认；固定 timeout 场景保留 124，不定义业务 TIME_LIMIT。
- 9 个一次性容器均按本次随机身份和精确 ID 清理并确认不存在；客户端超时、未知状态或清理失败不能变绿。
- CLI/daemon/镜像缺失的负向验证均在独立子进程完成，每项收集 1、setup error 1、退出 1，符合预期非零且无 skip；通过临时 PATH、无效 Unix DOCKER_HOST 或进程内替换为不存在的镜像引用注入，不停止 daemon、不删镜像、不改测试文件。
- 原始构建、检查和负向证据留在已忽略的 local-reference/runtime/m2-python-image/，含 base.json、build.log、image.json、smoke.log、smoke-summary.json、repository-checks.json、negative-checks.json。

## 学习与未验边界

- 为什么选当前方案：镜像只提供运行工具，语言表只提供不可变 argv/配置键，生产执行、身份映射与计量协议分节实现，避免把 tag 或工具输出当作可信判题结论。
- 我理解了什么：待用户用自己的话补充；哪里没懂/待补：digest 与 tag、构建层/运行身份、语言表与 Runner 分工、GNU 工具和可信计量的区别，均未代验个人掌握。
- M2.2 不建练习包；M2.1 冻结包和 E2/E3 待掌握状态不变，练习答案未回移。
- 未验证正式 DockerRunner、宿主专用 UID/GID 文件链路、输出配额、恶意文件采集、可信计量、Verdict、Celery/状态机、完整沙箱样例集与云上流程；time 样本只证明工具输出可解析，不是性能或计量精度证据。
- CI：未核验；本节为未提交工作区，本轮未查询远端 CI。本地回归和可信冒烟不代表 M2 里程碑或生产安全验收通过。
