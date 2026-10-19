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
