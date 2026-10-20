# Worker 环境探针

## 1 职责

为 WSL 中同 UID 的文件共享、非 root 写回和资源回收提供环境验收依据；不承担生产判题 Runner 或业务状态机。

## 2 涉及文件

| 文件 | 作用 |
| --- | --- |
| [worker_probe.py](../../backend/tools/worker_probe.py) | 环境验收入口与容器内探测逻辑 |
| [Dockerfile.dev](../../backend/Dockerfile.dev)、[构建忽略规则](../../backend/Dockerfile.dev.dockerignore) | 只携带探针，避免引入业务依赖和多余构建材料 |
| [test_worker_probe.py](../../backend/tests/docker/test_worker_probe.py) | 从独立进程核对真实退出码、内容与残留 |
| [conftest.py](../../backend/tests/conftest.py)、[pytest 配置](../../backend/pyproject.toml) | 隔离默认测试与显式 Docker 验收 |
| [Makefile](../../Makefile) | 提供统一的 probe 入口 |

## 3 调用链

1. pytest → 脚本 main() → run_probe()：每个场景使用独立 run_id，避免重跑复用旧结果。
2. container() → Worker → judge → 宿主核验：以内容 SHA-256、实际 UID/GID 和输出属主作为证据，路径相同或 root 能写都不足以验收。
3. finally → cleanup() → 测试侧复核：清理后的状态也是结果，主命令结束不代表验收结束。

## 4 关键决策

环境选择依据见 [ADR-016](../adr/ADR-016-wsl-development-environment.md)；以下约束分别防止：

- `--network none` 阻断容器对外访问；`--pull never` 在缺镜像时立即失败，避免把联网下载及其故障混进文件链路验收。
- `--read-only` 限制写入范围；配 `--tmpfs /tmp` 给临时写入留出口，并用 `PYTHONDONTWRITEBYTECODE=1` 避免字节码缓存写入干扰探针，防止把只读文件系统问题误判为挂载故障。
- 超时采用 `run -d → wait → kill → wait → inspect`，确认容器已 exited 且保留实际 137；仅让 docker run 客户端超时可能留下仍运行的容器。
- 递归删除前校验 `root.parent == Path("/tmp")`，且目录名必须精确为 `oj-worker-probe-{run_id}`，防止路径误传导致删除其他目录。
- judge 的 input 只读、output 单独可写，防止写回误改输入、污染内容校验依据，并将输出写权限限制在指定目录。

## 5 异常与边界

正常、主动失败、超时被杀的脚本退出码分别为 0、23、137；pytest 通过表示预期异常和清理断言成立，不表示三个场景都退出 0。
基础设施或清理失败不能变绿；清理失败单独报告，已取得的容器退出信息仍保留。
结论限于宿主与容器 UID 相同；跨 UID、生产隔离、Worker 自行调用 daemon 等范围见 [未验证边界](../learning/06.5-worker-probe.md)。

## 6 怎么测

在 WSL 仓库根目录，先确保后端依赖、本地基础镜像就绪，再执行：

```bash
uv run --project backend --locked --offline python backend/tools/worker_probe.py build
make probe
make probe
```

预期两遍均为 `3 passed, 1 deselected`；三场景保留 0/23/137，SHA-256 与属主断言成立，容器和临时目录均无残留。
默认 pytest 不收集 Docker 目录；`make probe` 显式选择 Docker 场景，缺依赖应失败，不能用 skip 代替验收。
镜像身份、构建网络证据边界与历史实测结果见 [06.5 记录](../learning/06.5-worker-probe.md)。
