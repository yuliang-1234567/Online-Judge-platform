# ADR-016 WSL2开发与环境验收

状态：WSL2目录选择已采纳；原生Engine、Desktop选择及探针待验收。决定日期：2026-10-19。

工程位于WSL2 Linux文件系统，例如~/projects/oj-platform，不在/mnt/d下开发；Windows D盘仅留文档备份。三份Word原件私有保存，Git只维护项目Markdown。

先评估Ubuntu中的原生Docker Engine，再考虑Docker Desktop。验收必须完成Worker写文件、判题容器读到同一文件、非root写输出、清理成功；路径同名不是验收结果。

本次只读检查：
- Ubuntu 24.04.3 LTS，WSL2内核6.6.87.2，systemd作为PID 1；工程目标文件系统ext4。
- 原生Git 2.43.0、Python 3.12.3可用。
- uv、Node/npm未安装。
- Ubuntu未检测到dockerd和Engine软件包，/var/run/docker.sock不存在。
- Windows存在Docker Desktop，但从WSL调用只返回集成不可用提示，未取得可用daemon或服务端版本。
- WSL提示localhost代理未映射至NAT环境，下载依赖时需要单独验证网络；本轮未修改代理。

阶段06只启动MySQL和Redis，API本地运行，不做API容器化。Dockerfile.dev及Worker环境探针放06末尾，限时半天；探针失败不阻塞认证切片，必须在本ADR和learning记录结果与原因。

本轮探针未运行，原因是尚未进入阶段06且当前无可用Docker daemon；这不是探针通过或失败的结论。版本升级、Engine安装和探针实现均未执行。
