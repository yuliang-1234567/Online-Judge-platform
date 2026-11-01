# 认证服务用本模块处理密码，鉴权依赖用它验签；这里只抛领域异常，HTTP 层负责状态码。
# 密码工作占线程与准入名额，JWT 只证明身份；账号是否存在、角色和状态仍须请求时查库。
import asyncio
import re
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

import anyio
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings

MAX_USER_ID = 18446744073709551615


class HashCapacityExceeded(Exception):
    pass


class CorruptPasswordHash(Exception):
    pass


class InvalidAccessToken(Exception):
    pass


# lifespan 为每个应用实例创建一个上下文，经 app.state 交给各请求的服务共享。
# hasher、dummy 和两槽 limiter 必须一起共享；逐请求新建会让并发上限失效。
# repr=False 避免调试表示带出 dummy 哈希，但不等于敏感数据已加密。
@dataclass(repr=False)
class PasswordContext:
    hasher: PasswordHasher
    limiter: anyio.CapacityLimiter
    dummy_hash: str


# 启动时先准备 dummy，避免首次不存在用户的请求额外承担初始化成本。
# 返回的准入池只属于本应用实例；多进程部署的总容量不是全局两个槽。
async def build_password_context() -> PasswordContext:
    hasher = PasswordHasher()
    # dummy 在应用启动时生成一次，避免不存在用户走廉价分支而暴露账号存在性。
    dummy = await anyio.to_thread.run_sync(hasher.hash, secrets.token_urlsafe(32))
    return PasswordContext(hasher, anyio.CapacityLimiter(2), dummy)


# with 进入时借一个槽，yield 才让调用方执行哈希；finally 在正常或异常退出时归还。
# 借槽失败不能 release；borrowed_tokens 是观察当前借用数的属性，不是方法。
@contextmanager
def hash_admission(ctx: PasswordContext) -> Iterator[None]:
    # 容量满立即拒绝，不能让无界排队的密码请求耗尽内存；不同应用实例不共享配额。
    try:
        ctx.limiter.acquire_nowait()
    except anyio.WouldBlock:
        raise HashCapacityExceeded from None
    try:
        yield
    finally:
        ctx.limiter.release()


# partial 传入的零参数任务交给线程，避免 Argon2 阻塞事件循环；返回值/异常留给调用方。
# Task 跟踪线程等待的完成状态；名额包住整个等待过程，不能随 HTTP 请求取消提前释放。
async def _password_work[T](ctx: PasswordContext, function: Callable[[], T]) -> T:
    with hash_admission(ctx):
        # run_sync 默认 abandon_on_cancel=False，
        # 不主动丢弃线程结果；底层还有默认线程池限额。
        # 本模块的 limiter 另限真实/dummy 密码任务，不能把两者当作同一个池。
        worker = asyncio.create_task(anyio.to_thread.run_sync(function))
        try:
            # 第一次 shield 隔开等待者的 Task.cancel()，防止它连带取消 worker。
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # 取消请求不能终止已经执行的 Argon2 线程。等线程真正结束才归还名额，
            # 否则攻击者反复断开连接，实际 CPU 并发会突破 limiter 的上限。
            # CancelScope 屏蔽外层 AnyIO 取消作用域；第二次 shield 继续保护 worker。
            # 循环还接住再次 Task.cancel()；这不是停止线程，也没有承诺取消会立即返回。
            with anyio.CancelScope(shield=True):
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                # 线程已结束才读取其异常，避免未取回异常的后台告警；不用它覆盖原取消。
                # worker 自身被取消时 exception() 会抛 CancelledError，因此先区分状态。
                if not worker.cancelled():
                    worker.exception()
            raise


# 服务层传入原密码，不 trim 或规范化；加盐交给 hasher，不能自行复用固定盐。
async def hash_password(password: str, *, ctx: PasswordContext) -> str:
    return await _password_work(ctx, partial(ctx.hasher.hash, password))


# 不匹配只返回 False，由服务映射统一 401；
# InvalidHashError 才包装成内部故障供 HTTP 返回 500。
# 其他校验异常继续传播，不能把服务故障吞成密码错误，也不能携带哈希回传或写日志。
async def verify_password(
    password: str, encoded_hash: str, *, ctx: PasswordContext
) -> bool:
    try:
        return await _password_work(
            ctx, partial(ctx.hasher.verify, encoded_hash, password)
        )
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # 损坏的存储值是内部故障，不是假装成错误密码；异常不携带哈希原文。
        raise CorruptPasswordHash from None


# dummy 只补一次昂贵校验，不证明账号存在；故意丢弃布尔结果，不返回可登录身份。
# 同池约束减少资源成本差异，不保证网络、查库和调度后的端到端恒定时间。
async def verify_dummy_password(password: str, *, ctx: PasswordContext) -> None:
    # 与真实账号使用同一线程池准入；即使偶然匹配 dummy 也不能签发身份。
    await verify_password(password, ctx.dummy_hash, ctx=ctx)


# 验签结果只携带不可变身份与时间，避免把 token 内的旧角色当作当前权限。
@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    issued_at: int
    expires_at: int


# 20 位先限制整数解析的输入规模；BIGINT UNSIGNED 的数值上界仍需转 int 后另查。
# 满 20 位不代表合法，最大值加一同样是 20 位；只接收无前导零的正十进制字符串。
def _parse_subject(value: object) -> int:
    # fullmatch 避免 $ 接受末尾换行；先限位数，避免超长整数解析耗费资源。
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 20
        or re.fullmatch(r"[1-9][0-9]*", value) is None
    ):
        raise InvalidAccessToken
    result = int(value)
    if result > MAX_USER_ID:
        raise InvalidAccessToken
    return result


# 签发输入来自已确认的用户行；精确 int 检查还排除 bool，调用错误不能冒充客户端 401。
# Unix 秒不依赖显示时区；payload 可被读取，签名防篡改但不加密内容。
def create_access_token(user_id: int, *, settings: Settings) -> str:
    if type(user_id) is not int or not 1 <= user_id <= MAX_USER_ID:
        raise ValueError("用户 ID 超出范围")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + settings.jwt_expire_minutes * 60,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


# 固定 HS256 白名单而不信任 header 自报算法；require 检查字段存在，不代替类型校验。
# SecretStr 仅在 encode/decode 的局部解包；不得打印 Settings 或密钥。
def decode_access_token(token: str, *, settings: Settings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
            leeway=0,
        )
        # PyJWT 2.15.1 内部 int() 会接受 float/数字字符串；必须检查原始 payload，
        # type(...) is int 也排除 bool，不能把库的时间校验误当成严格类型校验。
        if type(payload["iat"]) is not int or type(payload["exp"]) is not int:
            raise InvalidAccessToken
        # leeway=0 与这里的严格边界一致：未来 iat、到达 exp 或颠倒的生命周期均拒绝。
        now = int(time.time())
        if (
            not payload["iat"] <= now < payload["exp"]
            or payload["exp"] <= payload["iat"]
        ):
            raise InvalidAccessToken
        return AccessTokenClaims(
            _parse_subject(payload["sub"]), payload["iat"], payload["exp"]
        )
    except jwt.InvalidTokenError:
        raise InvalidAccessToken from None
