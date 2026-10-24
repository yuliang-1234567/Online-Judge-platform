"""Keep Docker tests outside default collection and ordinary CI runs."""

from pathlib import Path

import pytest


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Collect Docker scenarios only for the explicit docker marker expression."""
    # pytest 收集目录前调用此钩子；返回 True 是忽略目录，
    # 因此普通 CI 连 Docker 用例也不收集。
    docker_tests = Path(__file__).parent / "docker"
    markexpr = config.getoption("markexpr") or ""
    # 两个条件缺一不可：少了后半句，-m "not docker" 也会被放行。
    allow = "docker" in markexpr and "not docker" not in markexpr
    # 放行只限 docker 子树，仍由 pytest 按 -m 过滤；
    # 允许 docker and not slow 这类表达式。
    return collection_path.is_relative_to(docker_tests) and not allow
