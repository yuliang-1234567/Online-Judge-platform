"""Keep opt-in service tests outside default collection and ordinary CI runs."""

from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.getgroup("auth integration").addoption(
        "--auth-integration",
        action="store_true",
        default=False,
        help=(
            "Collect controlled auth integration tests; "
            "valid server ownership is required"
        ),
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Collect service scenarios only through their explicit entry options."""
    # 在收集前排除整棵集成子树，普通 pytest 不加载其 conftest、不读取真实配置。
    integration_tests = Path(__file__).parent / "integration"
    if collection_path.is_relative_to(integration_tests):
        return not config.getoption("auth_integration")
    docker_tests = Path(__file__).parent / "docker"
    markexpr = config.getoption("markexpr") or ""
    # 两个条件缺一不可：少了后半句，-m "not docker" 也会被放行。
    allow = "docker" in markexpr and "not docker" not in markexpr
    # 放行只限 docker 子树，仍由 pytest 按 -m 过滤；
    # 允许 docker and not slow 这类表达式。
    return collection_path.is_relative_to(docker_tests) and not allow
