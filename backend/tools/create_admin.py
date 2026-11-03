"""在 backend/ 用 python -m tools.create_admin 创建管理员。

导入不读取配置或连接数据库。
"""

import argparse
import asyncio
import getpass
import os
import re
import sys
import warnings
from collections.abc import Mapping, Sequence
from typing import TextIO

from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security import PasswordContext, build_password_context, hash_password
from app.repositories.user import UserRepository
from app.schemas.auth import RegisterRequest


# 错误只保存固定文案和退出码；不能包装驱动/Pydantic 原文或把配置对象带到日志。
class CommandError(Exception):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse 默认会复述未知参数；有人误传 --password 时也不能回显其值。
        raise CommandError("参数错误；请使用 --help 查看用法", 2)


def read_admin_password(
    environ: Mapping[str, str], stream: TextIO | None = None
) -> str:
    """终端默认隐藏输入两次；环境变量仅用于无终端的自动化场景。"""
    stream = sys.stdin if stream is None else stream
    if stream.isatty():
        try:
            # getpass 在无法隐藏时会告警并回退到回显输入；把告警转成错误以拒绝回退。
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("管理员密码：")
                confirmation = getpass.getpass("再次输入密码：")
        except (EOFError, getpass.GetPassWarning):
            raise CommandError("无法安全读取隐藏输入", 2) from None
        if password != confirmation:
            raise CommandError("两次输入的密码不一致", 2)
        return password
    password = environ.get("OJ_ADMIN_PASSWORD")
    if not password:
        raise CommandError("非交互运行须注入 OJ_ADMIN_PASSWORD", 2)
    print(
        "提示：环境变量赋值命令可能留在 shell 历史中，请使用安全注入。", file=sys.stderr
    )
    return password


def validate_admin_input(username: str, password: str) -> RegisterRequest:
    # 复用注册规则与原始密码，不 trim；ValidationError 可能带输入，不能透传。
    try:
        return RegisterRequest(username=username, password=password)
    except ValidationError:
        raise CommandError("用户名或密码不符合注册规则", 2) from None


def is_username_conflict(error: IntegrityError) -> bool:
    # MySQL 驱动没有独立 constraint_name。只解析 1062 消息末尾的键名字段，
    # 不匹配整句错误文案，不猜测未知格式；消息可能含凭据，绝不能输出。
    args = getattr(error.orig, "args", ())
    if len(args) < 2 or args[0] != 1062 or not isinstance(args[1], str):
        return False
    match = re.search(r"\bfor key (['`])(?P<key>[A-Za-z0-9_.]+)\1\Z", args[1])
    return match is not None and match["key"] in {
        "uk_users_username",
        "users.uk_users_username",
    }


async def create_admin(
    session: AsyncSession, data: RegisterRequest, passwords: PasswordContext
) -> int:
    """哈希在事务外；仓储不提交，begin 成功退出后才能向调用方报告成功。"""
    encoded = await hash_password(data.password, ctx=passwords)
    try:
        # 不预查用户名：并发与大小写碰撞最终由数据库唯一约束决定。
        # 只 INSERT，禁止把既有 USER 提权或覆盖既有管理员的密码/状态。
        async with session.begin():
            user = await UserRepository(session).create_admin(data.username, encoded)
    except IntegrityError as error:
        if is_username_conflict(error):
            raise CommandError("用户名已存在；未修改已有账号", 3) from None
        raise CommandError("管理员写入失败；请只读核查账号状态", 70) from None
    return user.id


def database_url(environ: Mapping[str, str]) -> SecretStr:
    # 不构造要求 Redis/JWT 的完整 Settings；只复用现有 URL 格式校验。
    try:
        return Settings.validate_database_url(SecretStr(environ["DATABASE_URL"]))
    except (KeyError, ValueError, TypeError):
        raise CommandError("DATABASE_URL 缺失或格式不合法", 2) from None


async def run(data: RegisterRequest, url: SecretStr) -> int:
    passwords = await build_password_context()
    engine = create_async_engine(
        url.get_secret_value(),
        echo=False,
        hide_parameters=True,
        poolclass=NullPool,
        connect_args={"init_command": "SET time_zone = '+00:00'", "connect_timeout": 5},
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            return await create_admin(session, data, passwords)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = SafeParser(description="一次性创建管理员；不提供提权、覆盖或密码参数。")
    parser.add_argument(
        "--username", required=True, help="3–32 个 ASCII 字母、数字或下划线"
    )
    try:
        # --help 在这里退出；此前仅建 parser，没有读取环境、密码或连接数据库。
        options = parser.parse_args(argv)
        password = read_admin_password(os.environ)
        data = validate_admin_input(options.username, password)
        url = database_url(os.environ)
        user_id = asyncio.run(run(data, url))
    except CommandError as error:
        print(str(error), file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        print("管理员创建已中断；请只读核查账号状态", file=sys.stderr)
        return 130
    except Exception:
        # 驱动异常可含 SQL/参数/URL；不打印异常，也不自动重试不确定的提交。
        print("管理员创建失败；请只读核查账号状态", file=sys.stderr)
        return 70
    print(f"管理员创建成功，id={user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
