# WSL迁移与环境检查

日期：2026-10-19。本节目标是在WSL Linux文件系统建立文档工作副本并核实环境，不进入阶段06。

三条验收：实际进程及工作目录属于WSL；三份Word和skill拷贝哈希一致；Git只初始化main且无远程。

结果：原生/usr/bin/python3在Linux工作目录执行，文件系统ext4；三份Word及skill四组SHA-256全部匹配；main已初始化，git remote -v为空。完整哈希保存在私有local-reference/copy-hashes.json。

环境：Ubuntu 24.04.3 LTS，WSL2，systemd，Git 2.43.0，Python 3.12.3；uv和Node/npm缺失。Ubuntu无原生Engine/socket，Windows Desktop的WSL集成不可用。代理提示尚待后续网络验证。详见 [ADR-016](../adr/ADR-016-wsl-development-environment.md)。

Ruff/pytest未运行：本轮是文档迁移与修订，没有Python工程与测试，WSL也未安装这两个工具。未声称CI通过。环境探针尚未运行，06末尾再限时验收。

AI使用记录：
- AI执行环境读取、文档转换、哈希检查及批准范围内的文档修订。
- 用户确定全部业务范围、协作约束、排期和Git署名。
- 待理解/确认：五类W5专项设计；M1编辑并发事务方案；Engine及环境探针。

## 环境准备与 06.1 补充（2026-10-19）

上文是迁移时的历史快照。当前 uv 已以普通用户安装在 `~/.local/bin/uv`，版本 0.13.1，未用 sudo，未改 shell profile；Node/npm 仍未安装。

Docker 安装使用过 `wsl.exe --user root`：用户本次事后认可。后续任何 root 操作或 sudoers 修改，均须先说明原因、列出完整命令并逐次获批；规则已写入根目录 AGENTS.md，本次认可不延续。

关键系统配置变更如下（不是软件包全部文件的清单）：

| 文件或设置 | 实际结果 |
| --- | --- |
| `/etc/apt/sources.list.d/docker.sources` | 新建官方 HTTPS 源：Ubuntu noble、stable、amd64；Signed-By 指向下列密钥 |
| `/etc/apt/keyrings/docker.asc` | 新建 Docker 官方仓库公钥；不是私钥 |
| `/usr/lib/systemd/system/docker.service`、`docker.socket`、`containerd.service` | 由官方软件包安装的 systemd 单元 |
| `/etc/systemd/system/multi-user.target.wants/docker.service` | 已创建链接，目标为 `/usr/lib/systemd/system/docker.service`，enabled |
| `/etc/systemd/system/multi-user.target.wants/containerd.service` | 已创建链接，目标为 `/usr/lib/systemd/system/containerd.service`，enabled |
| `/etc/systemd/system/sockets.target.wants/docker.socket` | 软件包安装时创建链接，目标为 `/usr/lib/systemd/system/docker.socket`，enabled |

APT 源文件 SHA-256：`8f33259a79a8149bed86c66e103fb4c3fa70f9219cd7ff315b6cc30988afef0c`；公钥 SHA-256：`1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570`。
安装了 docker-ce / cli 29.9.1、containerd.io 2.4.2、Buildx 0.38.0、Compose 5.6.0 及其依赖；同时 APT 升级 curl、libcurl4t64、libcurl3t64-gnutls 至 8.5.0-2ubuntu10.16。APT 首次获取 Docker 索引 TLS 握手失败，限定重试后从官方源成功安装，未关闭证书或签名校验。

普通用户调用原生 `/usr/bin/docker`，context 为 default，连接 `unix:///var/run/docker.sock`；客户端和服务端均为 29.9.1，Compose 为 v5.6.0。docker、containerd 服务 active 且 enabled。当前用户原本就在 docker 组，未重复改组；socket 为 root:docker、0660。没有修改 sudoers、`/etc/wsl.conf`、DNS、系统代理或镜像源替代地址；`/etc/docker/daemon.json` 尚不存在。

只读网络诊断：WSL 2.6.1.0，内核 6.6.87.2-microsoft-standard-WSL2；Windows 用户目录未找到 `.wslconfig`，`wslinfo --networking-mode` 实测为 nat；自动生成的 resolv.conf 使用 `10.255.255.254`。WSL 的 http/https/all/no_proxy（大小写）均未设置。两侧原生 curl 直连结果如下，时间为一次 HTTPS HEAD 请求总耗时，不是 ping RTT：

| 目标 | WSL | Windows |
| --- | --- | --- |
| registry-1.docker.io/v2/ | 8.074 s，连接超时，curl 28，无 HTTP 响应 | 8.009 s，连接超时，curl 28，无 HTTP 响应 |
| auth.docker.io/token | 8.075 s，连接超时，curl 28，无 HTTP 响应 | 8.012 s，连接超时，curl 28，无 HTTP 响应 |
| pypi.org/simple/ | 1.947 s，HTTP 200 | 0.618 s，HTTP 200 |
| github.com/ | 0.408 s，HTTP 200 | 0.457 s，HTTP 200 |

对照测试只给单次 curl 指定现有 Windows 代理，未保存配置：Windows 的 registry 返回 401（1.518 s），auth 的 GET 返回 200（0.630 s）；WSL 使用现有代理访问 registry 返回 401（0.908 s）、auth 返回 200（0.604 s）。401 表示已到达 registry 的认证入口。代理连接细节仅保存在私有 local-reference/ 中。

推断：当前 Docker Hub 直连链路/DNS 存在问题，已验证的代理尚未用于 Docker daemon；尚不能仅据本次结果断言 DNS 污染。`docker info` 的 HTTP/HTTPS/NO_PROXY 字段及 systemd 服务 Environment 均为空。网络方案由用户选择，本轮不改配置。此前两次 `docker run --rm hello-world` 均因连接 registry 超时失败；代理 curl 成功不等于 Docker 拉取或 Worker 探针通过。06.3、06.5 等待网络解决；探针结果以后记入 ADR-016。

06.1 新建 `.gitignore`、`.gitattributes`、`deploy/.env.example` 和 AGENTS.md：统一忽略私有材料及运行产物、文本 LF、环境模板只含空密钥/占位符。实际检查：35 个应忽略路径、14 个应可跟踪路径符合预期，所有忽略来源为仓库 `.gitignore`；5 个文件为 UTF-8/LF，无尾随空白；环境模板 17 个键无重复，密钥为空，URL 仅含占位符；四张 PNG 和 Git skill 字节不变。`git diff --check` 及新文件空白检查无发现；未检出令牌/私钥特征。Ruff 和 pytest 命令均因工具未安装、Python 工程/测试未初始化而未运行，不记作通过。

AI 使用记录补充：AI 执行只读诊断并在批准范围内编写 06.1 配置/规则；用户明确 root、网络及逐节提交边界，尚未审阅本节 diff；待确认网络方案及 06.1 提交，未进入 06.2。
