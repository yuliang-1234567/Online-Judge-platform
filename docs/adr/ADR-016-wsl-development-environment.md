# ADR-016 WSL2开发与环境验收

状态：WSL2与原生Engine可用；网络V1/V2已验证；容器直达宿主回环代理=不可达（预期），已结案；V3′直连验证待执行，Worker探针待验收。决定日期：2026-10-19。

工程位于WSL2 Linux文件系统，例如~/projects/oj-platform，不在/mnt/d下开发；Windows D盘仅留文档备份。三份Word原件私有保存，Git只维护项目Markdown。

先评估Ubuntu中的原生Docker Engine，再考虑Docker Desktop。验收必须完成Worker写文件、判题容器读到同一文件、非root写输出、清理成功；路径同名不是验收结果。

迁移时的只读检查（历史快照，后续实际结果见下文）：
- Ubuntu 24.04.3 LTS，WSL2内核6.6.87.2，systemd作为PID 1；工程目标文件系统ext4。
- 原生Git 2.43.0、Python 3.12.3可用。
- uv、Node/npm未安装。
- Ubuntu未检测到dockerd和Engine软件包，/var/run/docker.sock不存在。
- Windows存在Docker Desktop，但从WSL调用只返回集成不可用提示，未取得可用daemon或服务端版本。
- WSL提示localhost代理未映射至NAT环境，下载依赖时需要单独验证网络；本轮未修改代理。

阶段06只启动MySQL和Redis，API本地运行，不做API容器化。Dockerfile.dev及Worker环境探针放06末尾，限时半天；探针失败不阻塞认证切片，必须在本ADR和learning记录结果与原因。

迁移当时尚未进入阶段06，Engine尚未安装，Worker探针未运行；这段是历史快照，不代表现在的安装状态，也不是Worker探针通过或失败的结论。

## 2026-10-19 后续环境与网络验收

用户批准采用 WSL mirrored，并显式关闭 autoProxy；已重启 WSL，普通用户进程未注入代理环境变量。原生 Docker Engine/CLI 29.9.1、Compose v5.6.0 可用；uv 0.13.1 已安装。此前未安装的描述仅是迁移时快照。

经用户批准的四项 root 操作，已在 WSL 内以 LF heredoc 写入 Docker 服务 drop-in，重载 systemd 并重启 Docker。文件不存在 CRLF/BOM；systemctl 的 Environment 和 docker info 中的 HTTP/HTTPS/NO_PROXY 均已实际核对。具体代理连接信息只放私有 local-reference/，不写入仓库或客户端 proxies 配置。

2026-10-19 用户更新验收口径：V1/V2 保留；原 V3 作为预期边界结案，由新增 V3′验证普通容器直连能力：

| 编号 | 验收 | 当前结果 |
| --- | --- | --- |
| V1 | WSL 经现有代理到 registry 返回 401；直连官方 PyPI/GitHub 正常；本地 curl 不经过代理 | 通过，均实测；本地 HTTP 服务已停止且监听释放 |
| V2 | daemon 有效代理和 NO_PROXY 配置一致，hello-world 成功运行并清理 | 通过，hello-world 输出确认信息，退出码 0 |
| V3 | 容器直达宿主回环代理 | 容器直达宿主回环代理=不可达（预期）；已结案，不记作环境故障，测试容器已清理 |
| V3′ | 一次性普通容器不带代理变量，直连 https://pypi.org 与 http://archive.ubuntu.com | 待执行；记录状态码、耗时、失败方式并清理 |

原 V3 已按用户决定结案：不改代理监听范围、不改 host 网络、不改任何既有网络配置。V3′不通过时，仅清理并记录到本 ADR 和 learning，再停止等待用户。06.3 独立开始，不以 V3′完成为前提。网络测试不替代 06.5 的 Worker 文件挂载与清理验收。

## 待定：镜像 build 阶段代理（本轮不配置）

- daemon 拉取镜像的代理、build 执行步骤的代理、容器运行时代理是不同作用域。V3 即使通过，也不能直接宣称 build 的网络已经通过。
- 仅在客户端 shell export HTTP_PROXY/HTTPS_PROXY，不会独立触发 build arg 自动注入；需显式传入 --build-arg HTTP_PROXY / HTTPS_PROXY 等，从 shell 取值或直接赋值。客户端 config.json 的 proxies 也可自动提供 build args，但本项目当前不采用、不写入该配置。
- 容器/构建步骤的代理地址计划使用 host.docker.internal；不能复制 daemon 的 loopback 地址。原生 Linux Engine 需明确映射该名称到 host-gateway，并验证该路径确实能连接现有代理。地址是否可达必须实测，不能仅比较字符串。
- 不把代理写成 Dockerfile ENV，不在镜像或公开日志中保存实际代理端点。显式 build arg 方式、所用 builder 的名称映射、NO_PROXY 及连通性均待独立确认，在首次实际镜像构建前解决，不能等到 06.5 才首次排查。
- 本轮没有执行 docker build，没有配置 build 代理。

依据：[Docker build proxy arguments](https://docs.docker.com/build/building/variables/#proxy-arguments)、[Docker client proxy](https://docs.docker.com/engine/cli/proxy/)、[Linux host-gateway](https://docs.docker.com/reference/cli/docker/container/run/#add-entries-to-container-hosts-file---add-host)。

## 原 V3 观测与结案（2026-10-19）

普通 bridge 容器中宿主别名解析成功，但访问宿主回环代理返回 Connection refused，容器退出码为 1，已清理。用户确认这是预期边界，结论统一为“容器直达宿主回环代理=不可达（预期）”，不记作环境故障，也不以此要求修改代理或网络。

此前按旧验收口径暂停的事件已经结案；06.2 可独立提交，06.3 按用户批准的仅数据库/缓存方案推进。实际代理端点、宿主地址及原始诊断输出只留在私有 local-reference/。

V3′通过后，按用户决定将当前环境的 build 结论更新为“build 不需要代理”；该结论依据容器直连实测，真实镜像构建仍需在首次构建时验证，不虚构已完成 build。V3′待执行期间不配置 build 代理。
