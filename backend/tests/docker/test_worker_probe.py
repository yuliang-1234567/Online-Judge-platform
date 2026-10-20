"""Exercise real Docker exits and verify cleanup from outside the probe."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.docker


@pytest.mark.parametrize(
    ("case", "expected_exit"), [("success", 0), ("failure", 23), ("timeout", 137)]
)
def test_worker_probe(case, expected_exit):
    """Expected failures pass only when their real exits and cleanup agree."""
    process = subprocess.run(
        [sys.executable, str(BACKEND / "tools" / "worker_probe.py"), case],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.stdout, process.stderr
    report = json.loads(process.stdout)
    print(json.dumps(report, sort_keys=True))
    assert "error" not in report, report
    assert "cleanup_error" not in report, report
    assert process.returncode == expected_exit, report
    assert report["probe_exit_code"] == report["original_exit_code"] == expected_exit
    assert report["uid"] != 0
    worker, judge = report["containers"]
    assert worker["role"] == "worker" and worker["exit_code"] == 0
    assert judge["role"] == "judge" and judge["exit_code"] == expected_exit
    assert judge["timed_out"] == (case == "timeout")
    for item in (worker, judge):
        assert item["status"] == "exited"
        assert (item["uid"], item["gid"]) == (report["uid"], report["gid"])
        assert item["input_sha256"] == report["host_sha256"]
    assert report["host_sha256"] == report["worker_file_sha256"]
    assert (
        report["host_output_sha256"]
        == report["expected_output_sha256"]
        == judge["output_sha256"]
    )
    assert report["output_owner"] == [report["uid"], report["gid"]]
    assert report["cleanup"] == {
        "containers_remaining": [],
        "directory_removed": True,
    }
    assert not Path(report["directory"]).exists()
    remaining = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=oj.probe.run={report['run_id']}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert not remaining.stdout.strip()
