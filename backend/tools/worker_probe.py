"""Check disposable Worker/judge file sharing without application dependencies."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

IMAGE = "oj-worker-probe:dev"
BASE_IMAGE = "python:3.12-slim"
BACKEND = Path(__file__).resolve().parents[1]


def docker(*args, timeout=15):
    """Run a bounded Docker command and preserve failures."""
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(
            f"docker {args}: exit={result.returncode}; {result.stderr.strip()}"
        )
    return result.stdout.strip()


def digest(content):
    """Return the SHA-256 of bytes read by this process."""
    return hashlib.sha256(content).hexdigest()


def build():
    """Build from the locally available base without installing dependencies."""
    print(docker("image", "inspect", BASE_IMAGE, "--format", "{{json .RepoDigests}}"))
    result = subprocess.run(
        [
            "docker",
            "build",
            "--pull=false",
            "--network",
            "none",
            "--progress",
            "plain",
            "-f",
            str(BACKEND / "Dockerfile.dev"),
            "-t",
            IMAGE,
            str(BACKEND),
        ],
        timeout=120,
    )
    return result.returncode


def inside(role, root, case):
    """Perform the file operation inside a non-root container."""
    identity = {"uid": os.getuid(), "gid": os.getgid()}
    if identity["uid"] == 0:
        raise RuntimeError("Container UID must not be root")
    if role == "worker":
        content = (root / "seed.bin").read_bytes()
        (root / "input" / "marker.bin").write_bytes(content)
    else:
        content = Path("/work/marker.bin").read_bytes()
        output = b"probe-output:" + content
        Path("/out/output.bin").write_bytes(output)
        identity["output_sha256"] = digest(output)
    identity["input_sha256"] = digest(content)
    print(json.dumps(identity), flush=True)
    if role == "judge" and case == "failure":
        return 23
    if role == "judge" and case == "timeout":
        time.sleep(60)
    return 0


def container(role, case, root, run_id):
    """Start detached, wait, and inspect the actual terminated container."""
    name = f"oj-worker-probe-{run_id}-{role}"
    uid, gid = os.getuid(), os.getgid()
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "oj.probe=worker-env",
        "--label",
        f"oj.probe.run={run_id}",
        "--user",
        f"{uid}:{gid}",
        "--network",
        "none",
        "--pull",
        "never",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "1",
        "--pids-limit",
        "64",
    ]
    if role == "worker":
        args += ["--mount", f"type=bind,src={root},dst={root}"]
    else:
        args += [
            "--mount",
            f"type=bind,src={root / 'input'},dst=/work,readonly",
            "--mount",
            f"type=bind,src={root / 'output'},dst=/out",
        ]
    docker(*args, IMAGE, "inside", role, str(root), case)
    timed_out = False
    try:
        exit_code = int(docker("wait", name, timeout=3 if case == "timeout" else 15))
    except subprocess.TimeoutExpired:
        # Killing only the CLI leaves the detached container alive.
        timed_out = True
        docker("kill", "--signal", "KILL", name)
        exit_code = int(docker("wait", name))
    inspected = json.loads(docker("inspect", name))[0]
    state = inspected["State"]
    if state["Status"] != "exited" or state["ExitCode"] != exit_code:
        raise RuntimeError(f"Container termination not confirmed: {state}")
    if timed_out and exit_code != 137:
        raise RuntimeError(f"SIGKILL exit code must remain 137: {exit_code}")
    config, host = inspected["Config"], inspected["HostConfig"]
    if config["User"] != f"{uid}:{gid}" or host["NetworkMode"] != "none":
        raise RuntimeError("Unexpected container identity or network")
    if not host["ReadonlyRootfs"] or host["Privileged"] or "/tmp" not in host["Tmpfs"]:
        raise RuntimeError("Unexpected filesystem or privilege configuration")
    if "PYTHONDONTWRITEBYTECODE=1" not in config["Env"]:
        raise RuntimeError("Bytecode writes were not disabled")
    observed = json.loads(docker("logs", name))
    if (observed["uid"], observed["gid"]) != (uid, gid):
        raise RuntimeError(f"Actual container identity mismatch: {observed}")
    return {
        "role": role,
        "name": name,
        "exit_code": exit_code,
        "status": state["Status"],
        "timed_out": timed_out,
        **observed,
    }


def cleanup(root, run_id):
    """Remove only this run's containers and its validated temporary directory."""
    selector = f"label=oj.probe.run={run_id}"
    ids = docker("ps", "-aq", "--filter", selector).split()
    if ids:
        docker("rm", "-f", *ids)
    remaining = docker("ps", "-aq", "--filter", selector).split()
    if remaining:
        raise RuntimeError(f"Containers still exist: {remaining}")
    # Never turn an arbitrary caller-provided path into a recursive delete.
    if root.parent != Path("/tmp") or root.name != f"oj-worker-probe-{run_id}":
        raise RuntimeError(f"Refusing unexpected cleanup path: {root}")
    shutil.rmtree(root)
    if root.exists():
        raise RuntimeError(f"Temporary directory still exists: {root}")
    return {"containers_remaining": remaining, "directory_removed": True}


def run_probe(case):
    """Report original container exits separately from cleanup errors."""
    start = time.monotonic()
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise RuntimeError("Run the probe as the current non-root WSL user")
    endpoint = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    if endpoint != "unix:///var/run/docker.sock" or os.environ.get("DOCKER_HOST"):
        raise RuntimeError("Probe requires the local WSL Docker daemon")
    image_id = docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
    run_id = uuid.uuid4().hex
    root = Path("/tmp") / f"oj-worker-probe-{run_id}"
    root.mkdir(mode=0o700)
    report = {
        "case": case,
        "run_id": run_id,
        "directory": str(root),
        "uid": uid,
        "gid": gid,
        "image_id": image_id,
        "containers": [],
    }
    exit_code = 1
    try:
        (root / "input").mkdir(mode=0o700)
        (root / "output").mkdir(mode=0o700)
        marker = secrets.token_bytes(64)
        (root / "seed.bin").write_bytes(marker)
        report["host_sha256"] = digest((root / "seed.bin").read_bytes())
        worker = container("worker", "success", root, run_id)
        report["containers"].append(worker)
        report["worker_file_sha256"] = digest(
            (root / "input" / "marker.bin").read_bytes()
        )
        if (
            worker["exit_code"]
            or len(
                {
                    report["host_sha256"],
                    report["worker_file_sha256"],
                    worker["input_sha256"],
                }
            )
            != 1
        ):
            raise RuntimeError("Worker file does not match host marker")
        judge = container("judge", case, root, run_id)
        report["containers"].append(judge)
        if judge["input_sha256"] != report["host_sha256"]:
            raise RuntimeError("Judge did not read the same content")
        output = root / "output" / "output.bin"
        expected = b"probe-output:" + marker
        report["host_output_sha256"] = digest(output.read_bytes())
        report["expected_output_sha256"] = digest(expected)
        report["output_owner"] = [output.stat().st_uid, output.stat().st_gid]
        if (
            output.read_bytes() != expected
            or report["host_output_sha256"] != judge["output_sha256"]
            or report["output_owner"] != [uid, gid]
        ):
            raise RuntimeError("Output content or ownership mismatch")
        exit_code = judge["exit_code"]
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["original_exit_code"] = exit_code
        try:
            report["cleanup"] = cleanup(root, run_id)
        except Exception as error:
            report["cleanup_error"] = f"{type(error).__name__}: {error}"
            exit_code = 1
        report["probe_exit_code"] = exit_code
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return report


def main():
    """Expose build, scenario, and container-only entry points."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["build", "success", "failure", "timeout", "inside"]
    )
    parser.add_argument("details", nargs="*")
    arguments = parser.parse_args()
    if arguments.action == "build":
        return build()
    if arguments.action == "inside":
        role, root, case = arguments.details
        return inside(role, Path(root), case)
    report = run_probe(arguments.action)
    print(json.dumps(report, sort_keys=True))
    return report["probe_exit_code"]


if __name__ == "__main__":
    sys.exit(main())
