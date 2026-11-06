# create_app 安装本模块，将领域异常转为统一 HTTP 契约；内部原始异常不直接返回给客户端。
import logging
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.security import CorruptPasswordHash, HashCapacityExceeded

logger = logging.getLogger(__name__)


# 仅承载允许对外展示的文案与状态，不放密码/哈希/连接串；不可把原始异常正文直接塞入。
class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, *, retry_after: int | None = None
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


# request_id 让固定错误文案仍可定位日志；401 声明 Bearer，429 可带重试等待时间。
def error_response(request_id: str, error: AppError) -> JSONResponse:
    headers = {"X-Request-ID": request_id}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    if error.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request_id,
            }
        },
        status_code=error.status,
        headers=headers,
    )


# scope 提供请求元信息/state，receive 传递请求体或断连事件，send 发出响应事件。
# 本中间件透传 receive、不读取密码体；只包装 send 为成功和错误响应统一添加追踪头。
class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # 请求标识来自外部，限制字符和长度再写日志/响应头；
        # 无有效值则生成，不能承载凭据。
        supplied = (
            dict(scope.get("headers", []))
            .get(b"x-request-id", b"")
            .decode("ascii", errors="ignore")
        )
        request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        # response.start 是发送状态码和头的节点；
        # 移除下游同名头再加本次 ID，避免重复冲突。
        # nonlocal 让外层知道响应已开始；响应体事件照常转发，不重写业务 JSON。
        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message["headers"] = headers + [(b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # 原异常可能含 SQL 参数/哈希/Authorization；不记录异常正文与 traceback。
            # 在应用边界处理，避免 ServerErrorMiddleware 再抛出原异常给服务器日志。
            logger.error("request_failed request_id=%s", request_id)
            # HTTP 不能在已发状态码/部分响应体后再发一份 500；
            # 抛脱敏错误让服务器结束响应。
            if started:
                raise RuntimeError("响应已开始后发生内部错误") from None
            await error_response(
                request_id, AppError(500, "INTERNAL_ERROR", "服务内部错误")
            )(scope, receive, send_with_id)


# 注册处理器而非立即处理请求；已知领域异常分别映射，未知异常由外层中间件兜底。
def install_http_contract(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request.state.request_id, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic errors() 含 input，直接回传会泄漏密码；只返回固定契约文案。
        fields = sorted(
            {
                str(e["loc"][-1])
                for e in exc.errors()
                if e["loc"]
                and e["type"] != "extra_forbidden"
                and e["loc"][-1]
                in {
                    "username",
                    "password",
                    "role",
                    "status",
                    "page",
                    "size",
                    "cursor",
                    "limit",
                    "id",
                    "slug",
                    "title",
                    "description",
                    "difficulty",
                    "tag_ids",
                    "time_limit_ms",
                    "memory_limit_mb",
                    "name",
                    "case_index",
                    "input_data",
                    "expected_output",
                    "is_sample",
                }
            }
        )
        message = "请求参数不合法" + ("：" + "、".join(fields) if fields else "")
        return error_response(
            request.state.request_id, AppError(422, "VALIDATION_ERROR", message)
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        codes = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }
        return error_response(
            request.state.request_id,
            AppError(
                exc.status_code,
                codes.get(exc.status_code, "HTTP_ERROR"),
                "请求无法处理",
            ),
        )

    @app.exception_handler(HashCapacityExceeded)
    async def capacity_error(
        request: Request, exc: HashCapacityExceeded
    ) -> JSONResponse:
        # 本进程容量饱和不是依赖故障：返回 429，客户端按 Retry-After 重试。
        return error_response(
            request.state.request_id,
            AppError(429, "RATE_LIMITED", "请求过于频繁，请稍后重试", retry_after=1),
        )

    # 损坏哈希不是用户输错密码：只记录固定事件与请求 ID，保持 500 且不输出异常正文。
    @app.exception_handler(CorruptPasswordHash)
    async def corrupt_hash(request: Request, exc: CorruptPasswordHash) -> JSONResponse:
        logger.error("invalid_password_hash request_id=%s", request.state.request_id)
        return error_response(
            request.state.request_id, AppError(500, "INTERNAL_ERROR", "服务内部错误")
        )
