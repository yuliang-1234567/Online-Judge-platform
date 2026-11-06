import json
from copy import deepcopy

import pytest

from app.api import deps
from app.models.problem import Tag
from tests.api.test_admin_test_case import api as api
from tests.unit.test_problem_publication import PublicationCases, PublicationProblems
from tests.unit.test_problem_service import NOW, body
from tests.unit.test_test_case_service import case_row

ADMIN = "/api/v1/admin/problems"
PUBLIC = "/api/v1/problems"


@pytest.fixture
def publication(api, monkeypatch):
    monkeypatch.setattr(deps, "ProblemRepository", PublicationProblems)
    monkeypatch.setattr(deps, "TestCaseRepository", PublicationCases)
    api.store.cases[2] = case_row(
        2,
        case_index=7,
        is_sample=True,
        input_data="公开输入",
        expected_output="公开输出",
    )
    api.store.cases[3] = case_row(
        3, case_index=2, is_sample=True, input_data="另一样例", expected_output=""
    )
    api.store.links[1] = [1]
    return api


@pytest.mark.parametrize("action", ["publish", "offline"])
@pytest.mark.parametrize("user_id,expected", [(None, 401), (2, 403), (3, 403)])
def test_publication_requires_active_admin(publication, action, user_id, expected):
    response = publication.client.post(
        f"{ADMIN}/1/{action}", headers=publication.headers(user_id) if user_id else {}
    )
    assert response.status_code == expected
    assert not publication.store.audits


@pytest.mark.parametrize(
    "state,action,expected,target",
    [
        ("DRAFT", "publish", 200, "PUBLISHED"),
        ("OFFLINE", "publish", 200, "PUBLISHED"),
        ("PUBLISHED", "offline", 200, "OFFLINE"),
        ("PUBLISHED", "publish", 409, "PUBLISHED"),
        ("DRAFT", "offline", 409, "DRAFT"),
        ("OFFLINE", "offline", 409, "OFFLINE"),
    ],
)
def test_admin_transition_matrix(publication, state, action, expected, target):
    store = publication.store
    store.problems[1].status = state
    response = publication.client.post(
        f"{ADMIN}/1/{action}", headers=publication.headers()
    )
    assert response.status_code == expected and store.problems[1].status == target
    if expected == 200:
        assert response.json() == {"id": 1, "status": target}
        (audit,) = store.audits
        assert audit.action == f"{action.upper()}_PROBLEM"
        summary = json.loads(audit.payload_summary)
        expected_summary = {"before": state, "after": target}
        if action == "publish":
            expected_summary.update(case_count=3, budget_ms=29_000)
        assert summary == expected_summary
        assert audit.user_id == 1 and audit.resource_id == 1
    else:
        assert response.json()["error"]["code"] == "CONFLICT"
        assert not store.audits


@pytest.mark.parametrize(
    "gate,message",
    [
        ("empty", "发布至少需要一个测试点"),
        ("sample", "发布至少需要一个样例"),
        ("limits", "题目限制不合法，无法发布"),
        ("budget", "题目时间预算超过发布上限，请减少测试点或降低时限"),
    ],
)
def test_each_failed_gate_is_conflict_without_writes(publication, gate, message):
    store = publication.store
    if gate == "empty":
        store.cases.clear()
    elif gate == "sample":
        for row in store.cases.values():
            row.is_sample = False
    elif gate == "limits":
        store.problems[1].memory_limit_mb = 4_294_967_296
    else:
        store.problems[1].time_limit_ms = 160_000
    response = publication.client.post(
        f"{ADMIN}/1/publish", headers=publication.headers()
    )
    assert response.status_code == 409
    assert response.json()["error"]["message"] == message
    assert store.problems[1].status == "DRAFT" and not store.audits


def test_lowering_time_limit_via_put_can_publish_same_fifty_cases(publication):
    store, client, headers = (
        publication.store,
        publication.client,
        publication.headers(),
    )
    store.cases = {
        key: case_row(key, case_index=key, is_sample=key == 1) for key in range(1, 51)
    }
    store.problems[1].time_limit_ms = 1201
    assert client.post(f"{ADMIN}/1/publish", headers=headers).status_code == 409
    payload = body(time_limit_ms=1200)
    del payload["slug"]
    response = client.put(f"{ADMIN}/1", headers=headers, json=payload)
    assert response.status_code == 200 and response.json()["time_limit_ms"] == 1200
    assert client.post(f"{ADMIN}/1/publish", headers=headers).status_code == 200
    assert list(store.cases) == list(range(1, 51))
    assert json.loads(store.audits[-1].payload_summary)["budget_ms"] == 180_000


@pytest.mark.parametrize(
    "action,state", [("publish", "DRAFT"), ("offline", "PUBLISHED")]
)
@pytest.mark.parametrize("stage", ["update", "audit", "commit"])
def test_transition_fault_rolls_back(publication, action, state, stage):
    store = publication.store
    store.problems[1].status = state
    store.failure = stage
    response = publication.client.post(
        f"{ADMIN}/1/{action}", headers=publication.headers()
    )
    assert response.status_code == 500
    assert "private-storage-failure" not in response.text
    assert store.problems[1].status == state and not store.audits
    assert "rollback" in store.events


@pytest.mark.parametrize("action", ["publish", "offline"])
def test_missing_and_invalid_admin_problem_id(publication, action):
    headers = publication.headers()
    assert (
        publication.client.post(f"{ADMIN}/999/{action}", headers=headers).status_code
        == 404
    )
    assert (
        publication.client.post(f"{ADMIN}/0/{action}", headers=headers).status_code
        == 422
    )


def test_public_visibility_lifecycle_and_no_hidden_content(publication, caplog):
    client, headers, store = (
        publication.client,
        publication.headers(),
        publication.store,
    )
    assert client.get(f"{PUBLIC}/1").status_code == 404
    assert client.get(f"{PUBLIC}/999").status_code == 404
    assert client.get(PUBLIC).json() == {"items": [], "page": 1, "size": 20, "total": 0}
    assert client.post(f"{ADMIN}/1/publish", headers=headers).status_code == 200
    detail = client.get(f"{PUBLIC}/1")
    assert detail.status_code == 200
    payload = detail.json()
    summary = client.get(PUBLIC).json()["items"][0]
    assert set(summary) == {
        "id",
        "slug",
        "title",
        "difficulty",
        "time_limit_ms",
        "memory_limit_mb",
        "tags",
    }
    assert set(payload) == {*summary, "description", "samples"}
    assert payload["tags"] == [{"id": 1, "name": "数组"}]
    assert payload["samples"] == [
        {"case_index": 2, "input_data": "另一样例", "expected_output": ""},
        {"case_index": 7, "input_data": "公开输入", "expected_output": "公开输出"},
    ]
    for user in (1, 2, 3):
        assert (
            client.get(f"{PUBLIC}/1", headers=publication.headers(user)).json()
            == payload
        )
    assert "private-input" not in detail.text + caplog.text
    assert "private-output" not in detail.text + caplog.text
    history = deepcopy(store.history)
    store.inflight[1] = {"QUEUED"}
    assert client.post(f"{ADMIN}/1/offline", headers=headers).status_code == 200
    assert client.get(f"{PUBLIC}/1", headers=headers).status_code == 404
    assert client.get(PUBLIC).json()["total"] == 0 and store.history == history
    assert client.post(f"{ADMIN}/1/publish", headers=headers).status_code == 200
    assert client.get(f"{PUBLIC}/1").json() == payload


def test_public_pagination_and_filters(publication):
    store = publication.store
    store.tags[2] = Tag(id=2, name="模拟", created_at=NOW)
    for key, title, slug, difficulty, status, tags in [
        (1, "a%_/b", "one", "EASY", "PUBLISHED", [1, 2]),
        (2, "another", "a%_/b", "EASY", "PUBLISHED", [1]),
        (3, "a%_/b", "three", "HARD", "PUBLISHED", [1]),
        (4, "a%_/b", "four", "EASY", "OFFLINE", [1]),
        (5, "plain", "five", "EASY", "PUBLISHED", [2]),
    ]:
        row = deepcopy(store.problems[1])
        row.id, row.title, row.slug, row.difficulty, row.status = (
            key,
            title,
            slug,
            difficulty,
            status,
        )
        row.description = "description-only-keyword"
        store.problems[key], store.links[key] = row, tags
    params = {"difficulty": "EASY", "tag_id": 1, "q": " a%_/b ", "size": 1}
    for page, expected in [(1, [2]), (2, [1]), (3, [])]:
        response = publication.client.get(PUBLIC, params={**params, "page": page})
        assert response.status_code == 200
        payload = response.json()
        assert [row["id"] for row in payload["items"]] == expected
        assert payload["total"] == 2 and payload["page"] == page
    for params in ({"tag_id": 99}, {"q": "description-only-keyword"}):
        assert publication.client.get(PUBLIC, params=params).json()["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "size=0",
        "size=51",
        "difficulty=UNKNOWN",
        "tag_id=0",
        "tag_id=1&tag_id=2",
        "q=" + "x" * 129,
    ],
)
def test_public_filter_validation(publication, query):
    assert publication.client.get(f"{PUBLIC}?{query}").status_code == 422
