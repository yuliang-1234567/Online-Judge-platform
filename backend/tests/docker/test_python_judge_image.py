"""仅验证固定可信脚本的镜像能力；不是生产 Runner 或沙箱安全验收。"""

import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.docker
IMAGE_REF = "oj-judge-python:1"
SMOKE_LABEL = "m2-python-image"


@dataclass(frozen=True)
class Result:
    stdout: bytes
    stderr: bytes
    exit_code: int


def _docker(*args: str, data: bytes = b"", check: bool = True):
    """CLI 等待有界；客户端超时不证明容器停止，调用方仍须进入清理。"""
    result = subprocess.run(
        ["docker", *args],
        input=data,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"docker {args[0]} failed ({result.returncode}): "
            + result.stderr.decode("utf-8", errors="replace")[-1000:]
        )
    return result


def _inspect_container(reference: str):
    result = _docker("inspect", "--type", "container", reference, check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)[0]
    message = result.stderr.decode("utf-8", errors="replace").lower()
    # 只将 daemon 明确返回的不存在视为已清理；连接错误不能冒充无残留。
    if result.returncode == 1 and (
        "no such container" in message or "no such object" in message
    ):
        return None
    raise RuntimeError("Cannot confirm container state: " + message[-1000:])


def _assert_owned(info, name: str, token: str, image_id: str) -> None:
    """随机名称和标签必须同时匹配；后续操作只使用查实的精确 ID。"""
    assert info["Name"] == "/" + name
    assert info["Config"]["Labels"]["oj.smoke"] == SMOKE_LABEL
    assert info["Config"]["Labels"]["oj.smoke.run"] == token
    assert info["Image"] == image_id


def _cleanup(reference: str, name: str, token: str, image_id: str) -> None:
    info = _inspect_container(reference)
    if info is None:
        return
    _assert_owned(info, name, token, image_id)
    container_id = info["Id"]
    state = info["State"]["Status"]
    if state == "running":
        # 超时或断言失败也终止本容器；再 wait/inspect，而不是仅杀 Docker CLI。
        stopped = _docker("kill", "--signal", "KILL", container_id, check=False)
        current = _inspect_container(container_id)
        assert current is not None
        if stopped.returncode and current["State"]["Status"] != "exited":
            raise RuntimeError("Cannot confirm termination of owned smoke container")
        _docker("wait", container_id)
        info = _inspect_container(container_id)
        assert info is not None
        state = info["State"]["Status"]
    if state not in {"created", "exited"}:
        raise RuntimeError("Unknown smoke container state; preserving resource")
    _docker("rm", container_id)
    assert _inspect_container(container_id) is None


@pytest.fixture(scope="module")
def image_id() -> str:
    # 不自动拉镜像、启动 daemon 或 skip；显式 Docker 验收缺前提就必须失败。
    if shutil.which("docker") is None:
        pytest.fail("Docker CLI is required for image smoke tests", pytrace=False)
    try:
        _docker("version", "--format", "{{.Server.Os}}")
        info = json.loads(_docker("image", "inspect", IMAGE_REF).stdout)[0]
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        pytest.fail(f"Local judge image/daemon unavailable: {error}", pytrace=False)
    assert info["Os"] == "linux"
    config = info["Config"]
    assert config["User"] == "65532:65532"
    assert config["WorkingDir"] == "/work"
    assert not config.get("Entrypoint")
    assert config["Cmd"] == ["/usr/local/bin/python3", "--version"]
    assert not config.get("Volumes")
    print(
        json.dumps(
            {
                "image_ref": IMAGE_REF,
                "image_id": info["Id"],
                "platform": info["Os"] + "/" + info["Architecture"],
                "default_user": config["User"],
            },
            sort_keys=True,
        )
    )
    return info["Id"]


def _run(image_id: str, argv: tuple[str, ...], data: bytes = b"") -> Result:
    token = uuid.uuid4().hex
    name = "oj-m22-smoke-" + token
    container_id = None
    report = {"name": name, "image_id": image_id}
    try:
        created = _docker(
            "create",
            "--pull=never",
            "--interactive",
            "--name",
            name,
            "--label",
            "oj.smoke=" + SMOKE_LABEL,
            "--label",
            "oj.smoke.run=" + token,
            "--network=none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=1",
            "--pids-limit=64",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "core=0:0",
            "--log-driver=json-file",
            "--log-opt=max-size=1m",
            "--log-opt=max-file=1",
            image_id,
            *argv,
        )
        container_id = created.stdout.decode().strip()
        assert re.fullmatch(r"[0-9a-f]{64}", container_id)
        report["container_id"] = container_id
        info = _inspect_container(container_id)
        assert info is not None
        _assert_owned(info, name, token, image_id)
        assert info["State"]["Status"] == "created"
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert info["HostConfig"]["ReadonlyRootfs"]
        assert info["Config"]["User"] == "65532:65532"
        assert not info["HostConfig"].get("Binds")
        assert all(mount["Type"] == "tmpfs" for mount in info["Mounts"])
        # 在 start 前核验归属与挂载。传入完整 argv，不经 shell，也不挂宿主文件。
        attached = _docker(
            "start", "--attach", "--interactive", container_id, data=data, check=False
        )
        exit_code = int(_docker("wait", container_id).stdout.strip())
        info = _inspect_container(container_id)
        assert info is not None
        _assert_owned(info, name, token, image_id)
        assert info["State"]["Status"] == "exited"
        assert info["State"]["ExitCode"] == exit_code
        # attach 客户端可报告正常附着或程序退出；真实退出码由 wait+inspect 共同确认。
        assert attached.returncode in {0, exit_code}
        report.update(exit_code=exit_code, attach_exit=attached.returncode)
        return Result(attached.stdout, attached.stderr, exit_code)
    finally:
        # create 应答未知时可按预定随机名观察，但确认归属后才按精确 ID 清理。
        try:
            _cleanup(container_id or name, name, token, image_id)
        except Exception:
            report["cleanup_confirmed"] = False
            print(json.dumps(report, sort_keys=True))
            raise
        report["cleanup_confirmed"] = True
        print(json.dumps(report, sort_keys=True))


def _python(code: str) -> tuple[str, ...]:
    return ("/usr/local/bin/python3", "-B", "-u", "-c", code)


def test_image_default_command(image_id: str) -> None:
    result = _run(image_id, ())
    assert result.exit_code == 0
    assert result.stdout.startswith(b"Python 3.12.")
    assert result.stderr == b""


def test_python_version_and_default_identity(image_id: str) -> None:
    result = _run(
        image_id,
        _python(
            "import json,os,sys; "
            "print(json.dumps(dict(version=list(sys.version_info[:3]), "
            "uid=os.getuid(),gid=os.getgid())))"
        ),
    )
    assert result.exit_code == 0 and result.stderr == b""
    info = json.loads(result.stdout)
    assert info["version"][:2] == [3, 12]
    assert (info["uid"], info["gid"]) == (65532, 65532)
    print(json.dumps({"python_runtime": info}, sort_keys=True))


def test_python_stdio(image_id: str) -> None:
    result = _run(
        image_id,
        _python(
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); "
            "sys.stderr.buffer.write(b'stderr-marker\\n')"
        ),
        data=b"m22-input\r\n",
    )
    assert result.exit_code == 0
    assert result.stdout == b"m22-input\r\n"
    assert result.stderr == b"stderr-marker\n"


def test_nonzero_exit_is_preserved(image_id: str) -> None:
    result = _run(image_id, _python("import sys; print('exit-23'); sys.exit(23)"))
    assert result.exit_code == 23
    assert result.stdout == b"exit-23\n"
    assert result.stderr == b""


@pytest.mark.parametrize(
    ("command", "marker"),
    [
        (("/usr/bin/timeout", "--version"), b"GNU coreutils"),
        (("/usr/bin/time", "--version"), b"GNU Time"),
    ],
)
def test_gnu_tools_versions(image_id: str, command, marker: bytes) -> None:
    result = _run(image_id, command)
    assert result.exit_code == 0
    version = result.stdout + result.stderr
    assert marker in version
    print(json.dumps({"tool_version": version.decode().splitlines()[0]}))


def test_gnu_time_reports_parseable_values(image_id: str) -> None:
    result = _run(
        image_id,
        (
            "/usr/bin/time",
            "-f",
            "elapsed=%e maxrss=%M",
            *_python("print('timed-ok')"),
        ),
    )
    assert result.exit_code == 0 and result.stdout == b"timed-ok\n"
    # 只证明工具能报告数值；这里没有可信统计通道，也不验证判题计量精度。
    assert re.fullmatch(rb"elapsed=\d+(?:\.\d+)? maxrss=\d+\n", result.stderr)
    print(json.dumps({"tool_sample_only": result.stderr.decode().strip()}))


def test_gnu_timeout_terminates_trusted_sleep(image_id: str) -> None:
    result = _run(
        image_id,
        (
            "/usr/bin/timeout",
            "--kill-after=1s",
            "1s",
            *_python("import time; time.sleep(30)"),
        ),
    )
    # 124 是这个固定 GNU timeout 场景的工具退出码，不直接定义业务 TIME_LIMIT。
    assert result.exit_code == 124
    assert result.stdout == result.stderr == b""


def test_installed_package_versions(image_id: str) -> None:
    result = _run(image_id, ("/usr/bin/dpkg-query", "-W", "coreutils", "time"))
    assert result.exit_code == 0 and result.stderr == b""
    versions = dict(line.split("\t", 1) for line in result.stdout.decode().splitlines())
    assert set(versions) == {"coreutils", "time"}
    assert all(versions.values())
    print(json.dumps({"installed_packages": versions}, sort_keys=True))
