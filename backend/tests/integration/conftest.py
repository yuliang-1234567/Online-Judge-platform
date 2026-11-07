"""显式集成收集门禁；真实 MySQL 与 Redis 归属通过后才加载用例。"""

import os

import pytest

from tools.auth_integration import (
    CHILD_ENV_KEYS,
    RunnerError,
    load_application_settings,
    verify_server_ownership,
)

_SETTINGS = pytest.StashKey[object]()


def require_server_ownership() -> None:
    environment = {key: os.environ[key] for key in CHILD_ENV_KEYS if key in os.environ}
    try:
        verify_server_ownership(environment)
    except RunnerError as error:
        code = error.driver_code if error.driver_code is not None else error.exit_code
        raise pytest.UsageError(f"服务端归属核验失败，错误码 {code}") from None


def pytest_configure(config: pytest.Config) -> None:
    # historic hook 在加载此 conftest 时执行，早于该目录的测试模块导入。
    if not config.getoption("auth_integration"):
        raise pytest.UsageError("认证集成必须从受控入口显式开启")
    if _SETTINGS in config.stash:
        return  # 同一配置只映射一次；fixture 仅取缓存，不重复改环境。
    require_server_ownership()
    # 进程环境含 Python/pytest 的运行变量；只把四项应用配置交给严格键集校验。
    # 入口构造的子环境本身必须恰好四项，不能在入口静默过滤额外配置。
    environment = {key: os.environ[key] for key in CHILD_ENV_KEYS if key in os.environ}
    try:
        config.stash[_SETTINGS] = load_application_settings(environment)
    except (RunnerError, ValueError):
        raise pytest.UsageError("认证集成实际配置无效；原值不回显") from None


@pytest.fixture(scope="session")
def auth_integration_settings(pytestconfig: pytest.Config):
    try:
        return pytestconfig.stash[_SETTINGS]
    except KeyError:
        raise pytest.UsageError("认证集成配置尚未通过收集期门禁") from None


@pytest.fixture
def m1_application(auth_integration_settings):
    """M1 用例沿用双 owner 门禁；fixture 不读取部署配置。"""
    from m1_support import live_m1_application

    return lambda case: live_m1_application(auth_integration_settings, case)
