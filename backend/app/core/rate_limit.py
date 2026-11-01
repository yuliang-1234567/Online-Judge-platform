# 认证服务在哈希前查限流、失败后记账；本模块只管理配额，不判断密码或建立身份。
# Python 替身测试只验证调用协议，不能证明下面 Lua 在真实 Redis 中的执行结果。
import hashlib
import ipaddress
import logging
import math
import re

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.http import AppError

logger = logging.getLogger(__name__)

# INCR 与首次过期设置放在同一 Lua 内，防止进程在两条命令之间退出留下永不过期的键。
# 登录先读失败计数，失败后再记一次；已进入校验的并发请求不承诺严格五次总量。
RATE_LIMIT_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if ARGV[1] == 'consume' then
    count = redis.call('INCR', KEYS[1])
end
local ttl = redis.call('PTTL', KEYS[1])
if count > 0 and ttl < 0 then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    ttl = tonumber(ARGV[2])
end
return {count, ttl}
"""


# 客户端与前缀由 lifespan 注入并共享，关闭由 lifespan 负责，不为每次计数重建连接池。
class AuthRateLimiter:
    def __init__(self, redis: Redis, prefix: str) -> None:
        self.redis = redis
        self.prefix = prefix

    # 注册以规范化 IP 为身份；登录再拼小写用户名，NUL 分隔防止两部分拼接歧义。
    # 前缀隔离部署/测试命名空间，kind 隔开注册与登录；摘要不等于加密或匿名化保证。
    # 非法 IP 统一落到 unknown；不同用户名仍有不同键，不构成跨用户名的 IP 总限速。
    def _key(self, kind: str, ip: str, username: str = "") -> str:
        try:
            peer = ipaddress.ip_address(ip).compressed
        except ValueError:
            peer = "unknown"
        if kind == "login" and re.fullmatch(r"[A-Za-z0-9_]{3,32}", username) is None:
            raise AppError(422, "VALIDATION_ERROR", "请求参数不合法")
        # 登录先校验同款 ASCII 格式再小写，避免大小写变体绕过计数放大哈希负载。
        identity = f"{peer}\0{username.lower()}"
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return f"{self.prefix}:{kind}:{digest}"

    # EVAL 的 1 表示一个 KEYS；action 与窗口毫秒数放 ARGV，不能混淆参数位置。
    # Lua 返回 {count, ttl}，ttl 来自 PTTL，单位毫秒；接口收秒所以传入前乘 1000。
    # consume 加一，read 不加计数；已有计数却无 TTL 时，两者都会补过期时间。
    # 窗口从首次计数开始，不是整点清零；不把查配额与后续哈希合成一个事务。
    async def _evaluate(self, key: str, action: str, seconds: int) -> tuple[int, int]:
        result = await self.redis.eval(
            RATE_LIMIT_SCRIPT, 1, key, action, seconds * 1000
        )
        return int(result[0]), int(result[1])

    # Retry-After 用整数秒，向上取整避免客户端在窗口未过期时过早重试。
    # PTTL 可为负或零，最少给 1 秒；这个提示不承诺下次重试一定有配额。
    @staticmethod
    def _reject(ttl: int) -> None:
        raise AppError(
            429,
            "RATE_LIMITED",
            "请求过于频繁，请稍后重试",
            retry_after=max(1, math.ceil(ttl / 1000)),
        )

    # 注册按合法格式的尝试消费，包含重名；返回值已计入本次，第六次才因 > 5 拒绝。
    async def check_registration(self, ip: str) -> None:
        try:
            count, ttl = await self._evaluate(
                self._key("register", ip), "consume", 3600
            )
        except RedisError:
            # Redis 同时承担 broker，故障期暂停注册是已接受的降级，不绕开配额。
            raise AppError(503, "SERVICE_UNAVAILABLE", "认证服务暂时不可用") from None
        if count > 5:
            self._reject(ttl)

    # 登录此处尚未计入本次失败；已有五次失败就以 >= 5 阻止下一轮查库和哈希。
    # 查配额、哈希、记失败分三步，整体不原子；并发在途请求可能越过五次软边界。
    # Redis 故障时放行登录并只记固定告警，不声称此时仍有失败次数限流。
    async def check_login(self, ip: str, username: str) -> None:
        key = self._key("login", ip, username)
        try:
            count, ttl = await self._evaluate(key, "read", 60)
        except RedisError:
            logger.warning("login_rate_limit_unavailable")
            return
        if count >= 5:
            self._reject(ttl)

    # 只由统一 401 分支调用，使用与预查相同的键；成功登录不会在这里加失败次数。
    async def record_login_failure(self, ip: str, username: str) -> None:
        key = self._key("login", ip, username)
        try:
            await self._evaluate(key, "consume", 60)
        except RedisError:
            # 登录故障放行的边界保留；日志不包含 Redis URL、用户名或异常正文。
            logger.warning("login_rate_limit_unavailable")
