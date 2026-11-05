# 使用真实 app、JWT、父/子 router、服务与错误契约；只替换事务和仓储，不连真实依赖。
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
from app.main import create_app
from tests.unit.test_problem_service import (
    MemoryAudits,
    MemoryProblems,
    MemoryTags,
    Store,
    Transaction,
    body,
    db_error,
    problem,
)

ROUTES = [
    ("POST", "/api/v1/admin/problems"),
    ("GET", "/api/v1/admin/problems"),
    ("GET", "/api/v1/admin/problems/1"),
    ("PUT", "/api/v1/admin/problems/1"),
    ("GET", "/api/v1/admin/tags"),
    ("POST", "/api/v1/admin/tags"),
]


@pytest.fixture
def api(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline problem tests must not connect")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    settings = Settings(
        database_url="mysql+asyncmy://placeholder:placeholder@127.0.0.1:1/offline",
        redis_url="redis://127.0.0.1:1/4",
        jwt_secret="offline-problem-key-with-at-least-32-bytes",
    )
    store = Store()
    store.problems[1] = problem()
    store.links[1] = [1]
    app = create_app(settings)
    app.state.settings = settings

    class MemoryUsers:
        def __init__(self, tx):
            self.tx = tx

        async def by_id(self, key):
            return self.tx.users.get(key)

    async def session():
        yield Transaction(store)

    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(deps, "UserRepository", MemoryUsers)
    monkeypatch.setattr(deps, "ProblemRepository", MemoryProblems)
    monkeypatch.setattr(deps, "TagRepository", MemoryTags)
    monkeypatch.setattr(deps, "AuditLogRepository", MemoryAudits)
    client = TestClient(app, client=("2001:0db8::1", 5000))

    def headers(user_id=1):
        return {
            "Authorization": f"Bearer {create_access_token(user_id, settings=settings)}"
        }

    try:
        yield SimpleNamespace(app=app, client=client, store=store, headers=headers)
    finally:
        client.close()


def put_body(**changes):
    return {key: value for key, value in body(**changes).items() if key != "slug"}


def request(api, method, path, headers):
    data = None
    if method in {"POST", "PUT"}:
        data = (
            {"name": "新标签"}
            if path.endswith("/tags")
            else (body() if method == "POST" else put_body())
        )
    return api.client.request(method, path, headers=headers, json=data)


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("credential", [None, "Bearer malformed"])
def test_all_six_routes_require_identity(api, method, path, credential):
    response = request(
        api, method, path, {} if credential is None else {"Authorization": credential}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert len(api.store.problems) == 1 and api.store.audits == []


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("user_id", [2, 3])
def test_all_six_routes_reject_regular_or_disabled_user(api, method, path, user_id):
    response = request(api, method, path, api.headers(user_id))
    assert response.status_code == 403 and api.store.audits == []


def test_create_defaults_and_actor_are_server_owned(api):
    data = {
        key: value
        for key, value in body(slug="new-problem").items()
        if key not in {"tag_ids", "time_limit_ms", "memory_limit_mb"}
    }
    response = api.client.post(
        "/api/v1/admin/problems", headers=api.headers(), json=data
    )
    assert response.status_code == 201
    value = response.json()
    assert (
        value["status"],
        value["created_by"],
        value["time_limit_ms"],
        value["memory_limit_mb"],
        value["tags"],
    ) == ("DRAFT", 1, 1000, 256, [])
    assert value["title"] == "两数之和"
    assert value["created_at"] == "2026-11-05T02:00:00.123Z"
    assert set(value) == {
        "id",
        "slug",
        "title",
        "description",
        "difficulty",
        "time_limit_ms",
        "memory_limit_mb",
        "status",
        "created_by",
        "created_at",
        "updated_at",
        "tags",
    }
    audit = api.store.audits[0]
    assert audit.action == "CREATE_PROBLEM" and audit.user_id == 1
    assert audit.request_id == response.headers["X-Request-ID"]
    assert "private-description" not in audit.payload_summary


def test_put_replaces_six_fields_and_preserves_slug(api):
    response = api.client.put(
        "/api/v1/admin/problems/1",
        headers=api.headers(),
        json=put_body(tag_ids=[], time_limit_ms=4294967295, memory_limit_mb=1),
    )
    assert response.status_code == 200
    data = response.json()
    assert (
        data["slug"],
        data["time_limit_ms"],
        data["memory_limit_mb"],
        data["tags"],
    ) == ("old-slug", 4294967295, 1, [])
    assert api.store.audits[0].action == "UPDATE_PROBLEM"


@pytest.mark.parametrize("state", ["PUBLISHED", "OFFLINE"])
def test_put_non_draft_is_409(api, state):
    api.store.problems[1].status = state
    response = api.client.put(
        "/api/v1/admin/problems/1", headers=api.headers(), json=put_body()
    )
    assert response.status_code == 409 and api.store.audits == []
    assert api.store.problems[1].title == "old title"


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_missing_problem_is_404(api, method):
    response = request(api, method, "/api/v1/admin/problems/999", api.headers())
    assert response.status_code == 404 and api.store.audits == []


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "description",
        "difficulty",
        "tag_ids",
        "time_limit_ms",
        "memory_limit_mb",
    ],
)
@pytest.mark.parametrize("kind", ["missing", "null"])
def test_put_requires_all_six_non_null_fields(api, field, kind):
    data = put_body()
    if kind == "missing":
        del data[field]
    else:
        data[field] = None
    response = api.client.put(
        "/api/v1/admin/problems/1", headers=api.headers(), json=data
    )
    assert response.status_code == 422 and api.store.audits == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("slug", "changed"),
        ("status", "PUBLISHED"),
        ("created_by", 2),
        ("created_at", "2026-11-05"),
        ("updated_at", "2026-11-05"),
        ("password", "private-body-password"),
        ("unknown", "private-body-marker"),
    ],
)
def test_put_rejects_immutable_and_unknown_fields_safely(api, caplog, field, value):
    data = put_body(**{field: value})
    # put_body 不包含 slug，故显式添加以验证不可变字段而非测试辅助函数的过滤行为。
    data[field] = value
    response = api.client.put(
        "/api/v1/admin/problems/1", headers=api.headers(), json=data
    )
    assert response.status_code == 422
    assert "private-body-" not in response.text + caplog.text
    assert api.store.problems[1].slug == "old-slug" and api.store.audits == []


@pytest.mark.parametrize("field", ["time_limit_ms", "memory_limit_mb"])
@pytest.mark.parametrize("value", [0, -1, 4294967296, True, 1.5])
def test_limit_fields_reject_invalid_values(api, field, value):
    response = api.client.put(
        "/api/v1/admin/problems/1",
        headers=api.headers(),
        json=put_body(**{field: value}),
    )
    assert response.status_code == 422
    assert field in response.json()["error"]["message"] and api.store.audits == []


@pytest.mark.parametrize(
    "slug", ["Upper", "under_score", "-start", "end-", "a--b", "a\n", "", "a" * 65]
)
def test_slug_format_is_not_silently_normalized(api, slug):
    response = api.client.post(
        "/api/v1/admin/problems", headers=api.headers(), json=body(slug=slug)
    )
    assert response.status_code == 422 and api.store.audits == []


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"title": "a" * 129},
        {"description": " \n "},
        {"difficulty": "ROOT"},
        {"tag_ids": [1, 1]},
        {"tag_ids": [0]},
        {"tag_ids": [True]},
        {"status": "PUBLISHED"},
        {"created_by": 2},
        {"time_limit_ms": None},
    ],
)
def test_invalid_create_is_422_without_writes(api, changes):
    response = api.client.post(
        "/api/v1/admin/problems", headers=api.headers(), json=body(**changes)
    )
    assert response.status_code == 422 and len(api.store.problems) == 1
    assert api.store.audits == []


def test_missing_tag_is_422_without_implicit_creation(api):
    response = api.client.post(
        "/api/v1/admin/problems", headers=api.headers(), json=body(tag_ids=[999])
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "标签不存在"
    assert (
        len(api.store.tags) == 1
        and len(api.store.problems) == 1
        and api.store.audits == []
    )


def test_tag_is_explicitly_created_with_utc_response_and_audit(api):
    response = api.client.post(
        "/api/v1/admin/tags", headers=api.headers(), json={"name": " 新标签 "}
    )
    assert response.status_code == 201 and response.json()["name"] == "新标签"
    assert response.json()["created_at"] == "2026-11-05T02:00:00.123Z"
    audit = api.store.audits[0]
    assert (audit.action, audit.resource_type, audit.resource_id) == (
        "CREATE_TAG",
        "TAG",
        2,
    )


@pytest.mark.parametrize(
    "data", [{"name": " "}, {"name": "a" * 33}, {"name": None}, {"name": "ok", "id": 1}]
)
def test_invalid_tag_is_422(api, data):
    response = api.client.post("/api/v1/admin/tags", headers=api.headers(), json=data)
    assert (
        response.status_code == 422
        and len(api.store.tags) == 1
        and api.store.audits == []
    )


def test_both_lists_are_stable_pages_and_problem_list_excludes_body(api):
    for key, state in [(2, "PUBLISHED"), (3, "OFFLINE")]:
        obj = problem()
        obj.id, obj.slug, obj.status = key, f"problem-{key}", state
        obj.input_data = "private-hidden-input"
        api.store.problems[key] = obj
    result = api.client.get(
        "/api/v1/admin/problems?page=1&size=2", headers=api.headers()
    )
    assert result.status_code == 200
    assert [p["id"] for p in result.json()["items"]] == [3, 2]
    assert result.json()["total"] == 3
    assert "description" not in result.text and "private-hidden" not in result.text
    tail = api.client.get("/api/v1/admin/problems?page=2&size=2", headers=api.headers())
    assert [p["id"] for p in tail.json()["items"]] == [1]
    empty = api.client.get("/api/v1/admin/problems?page=9", headers=api.headers())
    assert empty.json()["items"] == [] and empty.json()["total"] == 3
    for name in ("标签2", "标签3"):
        api.client.post(
            "/api/v1/admin/tags", headers=api.headers(), json={"name": name}
        )
    tags = api.client.get("/api/v1/admin/tags?page=1&size=2", headers=api.headers())
    assert [tag["id"] for tag in tags.json()["items"]] == [3, 2]


@pytest.mark.parametrize("path", ["/problems", "/tags"])
@pytest.mark.parametrize("query", ["page=0", "size=0", "size=51"])
def test_list_bounds_are_422(api, path, query):
    response = api.client.get(
        "/api/v1/admin" + path + "?" + query, headers=api.headers()
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "stage,error,status",
    [
        ("create", db_error(1062, "private value for key 'uk_problems_slug'"), 409),
        ("create", db_error(1062, "private value for key 'uk_tags_name'"), 409),
        (
            "links",
            db_error(
                1452, "private CONSTRAINT 'fk_problem_tags_tag' FOREIGN KEY (tag_id)"
            ),
            422,
        ),
        ("links", db_error(1062, "private value for key 'PRIMARY'"), 500),
        ("audit", RuntimeError("private-audit-payload"), 500),
        ("commit", RuntimeError("private-commit-payload"), 500),
    ],
)
def test_database_failure_responses_are_safe_and_atomic(
    api, caplog, stage, error, status
):
    api.store.failure, api.store.failure_error = stage, error
    response = api.client.post(
        "/api/v1/admin/problems", headers=api.headers(), json=body()
    )
    assert response.status_code == status
    assert (
        len(api.store.problems) == 1
        and api.store.links == {1: [1]}
        and api.store.audits == []
    )
    assert "private-" not in response.text + caplog.text
    assert "PRIVATE SQL" not in response.text + caplog.text
    assert "create" in api.store.events and "rollback" in api.store.events
    if stage == "commit":
        assert "audit" in api.store.events


def assert_413(api, response):
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "VALIDATION_ERROR" not in response.text and "422" not in response.text
    assert len(api.store.problems) == 1 and api.store.audits == []


def test_300k_body_is_413_before_field_validation(api):
    # 同时含非法枚举；必须先由接收限额拒绝，而不能落到字段级 422。
    response = api.client.post(
        "/api/v1/admin/problems",
        headers=api.headers(),
        json=body(description="a" * (300 * 1024), difficulty="INVALID"),
    )
    assert_413(api, response)


def test_valid_200k_body_still_parses_and_commits(api):
    response = api.client.post(
        "/api/v1/admin/problems",
        headers=api.headers(),
        json=body(description="a" * (200 * 1024)),
    )
    assert response.status_code == 201
    assert len(response.json()["description"]) == 200 * 1024
    assert len(api.store.problems) == 2 and len(api.store.audits) == 1


def test_understated_content_length_does_not_bypass_actual_bytes(api):
    response = api.client.post(
        "/api/v1/admin/problems",
        headers={**api.headers(), "Content-Length": "8"},
        content=json.dumps(body(description="a" * (300 * 1024))).encode(),
    )
    assert_413(api, response)


@pytest.mark.parametrize(("kilobytes", "expected"), [(200, 201), (300, 413)])
def test_no_content_length_multi_chunk_receive_is_counted(api, kilobytes, expected):
    # 直接给真实 app 多个 ASGI body 帧，避免测试客户端合并分块后掩盖计数问题。
    raw = json.dumps(body(description="a" * (kilobytes * 1024))).encode()
    chunks = [raw[i : i + 65536] for i in range(0, len(raw), 65536)]
    incoming = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    outgoing = []
    auth = api.headers()["Authorization"].encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "POST",
        "path": "/api/v1/admin/problems",
        "raw_path": b"/api/v1/admin/problems",
        "query_string": b"",
        "headers": [(b"authorization", auth), (b"content-type", b"application/json")],
        "client": ("::1", 5000),
        "server": ("testserver", 80),
    }

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message):
        outgoing.append(message)

    asyncio.run(api.app(scope, receive, send))
    start = next(m for m in outgoing if m["type"] == "http.response.start")
    response_body = b"".join(
        m.get("body", b"") for m in outgoing if m["type"] == "http.response.body"
    )
    data = json.loads(response_body)
    headers = dict(start["headers"])
    assert start["status"] == expected
    if expected == 413:
        assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert data["error"]["request_id"] == headers[b"x-request-id"].decode()
        assert len(api.store.problems) == 1 and api.store.audits == []
    else:
        assert len(data["description"]) == kilobytes * 1024
        assert len(api.store.problems) == 2 and len(api.store.audits) == 1
