"""Keep Docker tests outside default collection and ordinary CI runs."""

from pathlib import Path

import pytest


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Collect Docker scenarios only for the explicit docker marker expression."""
    docker_tests = Path(__file__).parent / "docker"
    markexpr = config.getoption("markexpr") or ""
    allow = "docker" in markexpr and "not docker" not in markexpr
    return collection_path.is_relative_to(docker_tests) and not allow
