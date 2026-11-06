# 真实应用/鉴权/路由/服务，存储由可回滚替身替代；禁止真实 socket 连接。
import asyncio
import json
import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings
from app.core.db import get_session
from app.core.security import create_access_token
from tests.unit.test_problem_service import MemoryAudits, MemoryTags, db_error
from tests.unit.test_test_case_service import (
    CaseStore,
    CaseTransaction,
    LockedProblems,
    MemoryCases,
    case_body,
    case_row,
)

PREFIX = "/api/v1/admin"
ROUTES = [
    ("GET", "/problems/1/test-cases"),
    ("POST", "/problems/1/test-cases"),
    ("PUT", "/test-cases/1"),
    ("DELETE", "/test-cases/1"),
]


@pytest.fixture
def api(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline test-case tests must not connect")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="offline-test-case-key-with-at-least-32-bytes",
    )
    from app.main import create_app

    store = CaseStore()
    store.cases[1] = case_row()
    app = create_app(settings)
    app.state.settings = settings

    class Users:
        def __init__(self, tx):
            self.tx = tx

        async def by_id(self, key):
            return self.tx.users.get(key)

    async def session():
        yield CaseTransaction(store)

    app.dependency_overrides[get_session] = session
    for name, replacement in (
        ("UserRepository", Users),
        ("ProblemRepository", LockedProblems),
        ("TagRepository", MemoryTags),
        ("TestCaseRepository", MemoryCases),
        ("AuditLogRepository", MemoryAudits),
    ):
        monkeypatch.setattr(deps, name, replacement)
    client = TestClient(app, client=("2001:0db8::1", 5000))

    def headers(user_id=1):
        return {
            "Authorization": "Bearer " + create_access_token(user_id, settings=settings)
        }

    try:
        yield SimpleNamespace(app=app, client=client, store=store, headers=headers)
    finally:
        client.close()


def call(api, method, path, headers=None, **changes):
    options = {"headers": api.headers() if headers is None else headers}
    if method in {"POST", "PUT"}:
        options["json"] = case_body(case_index=2, **changes)
    return api.client.request(method, PREFIX + path, **options)


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("credential", [None, "Bearer malformed", 2, 3])
def test_all_test_case_routes_protect_hidden_content(api, method, path, credential):
    headers = (
        api.headers(credential)
        if isinstance(credential, int)
        else ({} if credential is None else {"Authorization": credential})
    )
    response = call(api, method, path, headers=headers)
    assert response.status_code == (403 if isinstance(credential, int) else 401)
    assert (
        "private-input" not in response.text and "private-output" not in response.text
    )
    assert list(api.store.cases) == [1] and not api.store.audits


@pytest.mark.parametrize("state", ["DRAFT", "OFFLINE"])
def test_create_update_delete_and_admin_full_read(api, state):
    api.store.problems[1].status = state
    response = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(case_index=8, input_data="", expected_output="  \r\n"),
    )
    assert response.status_code == 201
    result = response.json()
    assert result["input_size"] == 0 and result["output_size"] == 4
    assert result["expected_output"] == "  \r\n" and not result["is_sample"]
    assert result["created_at"].endswith(".123Z") and result["updated_at"].endswith(
        ".123Z"
    )
    updated = api.client.put(
        PREFIX + f"/test-cases/{result['id']}",
        headers=api.headers(),
        json=case_body(case_index=6, is_sample=True, input_data="中\n"),
    )
    assert updated.status_code == 200 and updated.json()["input_size"] == 4
    listing = api.client.get(
        PREFIX + "/problems/1/test-cases?size=1", headers=api.headers()
    )
    assert listing.status_code == 200 and listing.json()["total"] == 2
    assert listing.json()["items"][0]["case_index"] == 1
    assert listing.json()["items"][0]["input_data"] == "private-input\n"
    response = api.client.delete(
        PREFIX + f"/test-cases/{result['id']}", headers=api.headers()
    )
    assert response.status_code == 204 and response.content == b""
    assert [row.action for row in api.store.audits] == [
        "CREATE_TEST_CASE",
        "UPDATE_TEST_CASE",
        "DELETE_TEST_CASE",
    ]
    assert "private-input" not in "".join(
        row.payload_summary for row in api.store.audits
    )


@pytest.mark.parametrize("method,path", ROUTES[1:])
def test_published_case_writes_are_409(api, method, path):
    api.store.problems[1].status = "PUBLISHED"
    response = call(api, method, path)
    assert response.status_code == 409
    assert list(api.store.cases) == [1] and not api.store.audits


@pytest.mark.parametrize("method,path", ROUTES[1:])
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_inflight_case_writes_are_409_without_business_or_audit(
    api, method, path, state
):
    api.store.inflight[1] = state
    response = call(api, method, path)
    assert response.status_code == 409
    assert api.store.cases[1].case_index == 1 and not api.store.audits


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/problems/999/test-cases"),
        ("POST", "/problems/999/test-cases"),
        ("PUT", "/test-cases/999"),
        ("DELETE", "/test-cases/999"),
    ],
)
def test_missing_resources_are_404(api, method, path):
    assert call(api, method, path).status_code == 404
    assert not api.store.audits


@pytest.mark.parametrize(
    "field", ["case_index", "is_sample", "input_data", "expected_output"]
)
@pytest.mark.parametrize("invalid", ["missing", "null"])
def test_put_requires_four_non_null_fields(api, field, invalid):
    values = case_body()
    if invalid == "missing":
        values.pop(field)
    else:
        values[field] = None
    response = api.client.put(
        PREFIX + "/test-cases/1", headers=api.headers(), json=values
    )
    assert response.status_code == 422 and field in response.json()["error"]["message"]
    assert not api.store.audits


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_index", 0),
        ("case_index", -1),
        ("case_index", 4294967296),
        ("case_index", True),
        ("case_index", 1.5),
        ("case_index", "1"),
        ("is_sample", 1),
        ("is_sample", "false"),
        ("input_data", 123),
        ("expected_output", 123),
    ],
)
def test_types_and_index_bounds_are_422(api, field, value):
    response = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(**{field: value}),
    )
    assert response.status_code == 422 and not api.store.audits


@pytest.mark.parametrize(
    "field",
    [
        "problem_id",
        "id",
        "input_size",
        "output_size",
        "sha256",
        "created_at",
        "updated_at",
        "password",
        "unknown-private-field",
    ],
)
def test_server_fields_and_unknown_input_are_not_echoed(api, caplog, field):
    response = api.client.put(
        PREFIX + "/test-cases/1",
        headers=api.headers(),
        json={**case_body(), field: "private-full-request-marker"},
    )
    assert response.status_code == 422
    assert "private-full-request-marker" not in response.text + caplog.text
    assert "password" not in response.text + caplog.text
    assert "unknown-private-field" not in response.text + caplog.text


@pytest.mark.parametrize("field", ["input_data", "expected_output"])
@pytest.mark.parametrize("extra,status", [(0, 201), (1, 422)])
def test_utf8_limit_is_bytes_not_characters(api, field, extra, status):
    # 正好 1MiB 含多字节字符；额外一个 ASCII 字节即超过上限。
    text = "中" * (1048576 // 3) + "a" * (1 + extra)
    response = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(case_index=2, **{field: text}),
    )
    assert response.status_code == status
    if status == 201:
        size_field = "input_size" if field == "input_data" else "output_size"
        assert response.json()[size_field] == 1048576
    else:
        assert not api.store.audits


def test_each_field_can_reach_one_mib_together(api):
    response = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(
            case_index=2, input_data="x" * 1048576, expected_output="y" * 1048576
        ),
    )
    assert response.status_code == 201
    assert response.json()["input_size"] == response.json()["output_size"] == 1048576


def test_default_sample_flag_and_max_index(api):
    values = case_body(case_index=4294967295)
    del values["is_sample"]
    response = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=values,
    )
    assert response.status_code == 201 and response.json()["is_sample"] is False


def test_duplicate_index_409_and_fifty_first_422(api):
    duplicate = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(),
    )
    assert duplicate.status_code == 409 and not api.store.audits
    api.store.cases = {i: case_row(i, case_index=i) for i in range(1, 51)}
    full = api.client.post(
        PREFIX + "/problems/1/test-cases",
        headers=api.headers(),
        json=case_body(case_index=51),
    )
    assert (
        full.status_code == 422 and len(api.store.cases) == 50 and not api.store.audits
    )


def test_conflicting_update_rolls_back_and_does_not_reindex(api):
    api.store.cases[2] = case_row(2, case_index=9)
    response = api.client.put(
        PREFIX + "/test-cases/2",
        headers=api.headers(),
        json=case_body(),
    )
    assert response.status_code == 409
    assert api.store.cases[2].case_index == 9 and not api.store.audits


def test_stable_pagination_empty_pages_and_problem_dto_stays_separate(api):
    api.store.cases[2] = case_row(2, case_index=9)
    api.store.cases[3] = case_row(3, case_index=4)
    response = api.client.get(
        PREFIX + "/problems/1/test-cases?page=2&size=2", headers=api.headers()
    )
    assert response.status_code == 200
    assert [item["case_index"] for item in response.json()["items"]] == [9]
    empty = api.client.get(
        PREFIX + "/problems/1/test-cases?page=3&size=2", headers=api.headers()
    )
    assert empty.json()["items"] == [] and empty.json()["total"] == 3
    detail = api.client.get(PREFIX + "/problems/1", headers=api.headers())
    assert "input_data" not in detail.json() and "private-input" not in detail.text
    assert not api.store.audits


@pytest.mark.parametrize("query", ["page=0", "size=0", "size=51"])
def test_case_pagination_bounds(api, query):
    response = api.client.get(
        PREFIX + "/problems/1/test-cases?" + query, headers=api.headers()
    )
    assert response.status_code == 422


@pytest.mark.parametrize("state", ["DRAFT", "OFFLINE"])
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("field", ["time_limit_ms", "memory_limit_mb"])
def test_problem_put_current_limits_and_inflight_guard(api, state, changed, field):
    api.store.problems[1].status = state
    api.store.inflight[1] = "RUNNING"
    data = {
        "title": "new title",
        "description": "new description",
        "difficulty": "EASY",
        "tag_ids": [],
        "time_limit_ms": 2000 if changed else 1000,
        "memory_limit_mb": 256,
    }
    data["time_limit_ms"] = 1000
    if changed:
        data[field] = 2000
    response = api.client.put(PREFIX + "/problems/1", headers=api.headers(), json=data)
    assert response.status_code == (409 if changed else 200)
    assert len(api.store.audits) == (0 if changed else 1)
    assert api.store.problems[1].time_limit_ms == 1000


@pytest.mark.parametrize(
    "stage,error,status",
    [
        ("create", db_error(1062, "private value for key 'uk_cases_problem_idx'"), 409),
        ("create", db_error(1062, "private value for key 'PRIMARY'"), 500),
        ("create", db_error(1452, "private foreign-key-payload"), 500),
        ("audit", RuntimeError("private-audit-payload"), 500),
        ("commit", RuntimeError("private-commit-payload"), 500),
    ],
)
def test_case_failures_are_safe_and_atomic(api, caplog, stage, error, status):
    api.store.failure, api.store.failure_error = stage, error
    response = call(api, "POST", "/problems/1/test-cases")
    assert response.status_code == status
    assert list(api.store.cases) == [1] and not api.store.audits
    assert "private-" not in response.text + caplog.text
    assert "PRIVATE SQL" not in response.text + caplog.text
    assert "create" in api.store.events
    if stage == "commit":
        assert "audit" in api.store.events


def stream_json(amount, *, problem=False):
    # 64KiB 固定块反复产生；不拼完整大字符串/JSON/bytes，也不存储全部输入帧。
    if problem:
        yield b'{"slug":"stream","title":"stream","description":"'
        suffix = b'","difficulty":"EASY"}'
    else:
        yield b'{"case_index":2,"input_data":"'
        suffix = b'","expected_output":"","is_sample":false}'
    block = b"x" * 65536
    while amount:
        size = min(amount, len(block))
        yield block if size == len(block) else block[:size]
        amount -= size
    yield suffix


def streamed_request(api, amount, *, framing="absent", problem=False):
    pieces = stream_json(amount, problem=problem)
    outgoing, sizes = [], []
    path = PREFIX + ("/problems" if problem else "/problems/1/test-cases")
    headers = [
        (b"authorization", api.headers()["Authorization"].encode()),
        (b"content-type", b"application/json"),
    ]
    if framing == "small":
        headers.append((b"content-length", b"1"))
    elif framing == "chunked":
        headers.append((b"transfer-encoding", b"chunked"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("::1", 5000),
        "server": ("testserver", 80),
    }

    async def receive():
        piece = next(pieces, None)
        if piece is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        sizes.append(len(piece))
        return {"type": "http.request", "body": piece, "more_body": True}

    async def send(message):
        outgoing.append(message)

    try:
        asyncio.run(api.app(scope, receive, send))
    finally:
        pieces.close()
    start = next(m for m in outgoing if m["type"] == "http.response.start")
    data = json.loads(
        b"".join(
            m.get("body", b"") for m in outgoing if m["type"] == "http.response.body"
        )
    )
    assert max(sizes) <= 65536 and len(sizes) > 1
    return start, data


@pytest.mark.parametrize("framing", ["absent", "small", "chunked"])
def test_actual_sixteen_mib_limit_uses_streamed_bytes(api, framing):
    start, data = streamed_request(api, 16 * 1024 * 1024, framing=framing)
    assert start["status"] == 413
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert (
        data["error"]["request_id"] == dict(start["headers"])[b"x-request-id"].decode()
    )
    assert "VALIDATION_ERROR" not in json.dumps(data) and not api.store.audits
    assert list(api.store.cases) == [1]


def test_valid_case_above_256_kib_parses_and_commits(api):
    start, data = streamed_request(api, 1048576)
    assert start["status"] == 201 and data["input_size"] == 1048576
    assert len(api.store.cases) == 2 and len(api.store.audits) == 1


def test_original_problem_256_kib_limit_is_not_relaxed(api):
    start, data = streamed_request(api, 300 * 1024, problem=True)
    assert start["status"] == 413 and data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert not api.store.audits and len(api.store.problems) == 1
