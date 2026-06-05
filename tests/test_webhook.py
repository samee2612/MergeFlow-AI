import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.pipeline import is_backend_relevant_pr


WEBHOOK_SECRET = "test-secret"


@pytest.fixture(autouse=True)
def configure_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _payload(
    action: str,
    *,
    merged: bool = False,
    changed_files: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "repository": {"full_name": "owner/repo", "default_branch": "main"},
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "merged": merged,
            "merged_at": "2026-06-03T17:00:00Z",
            "user": {"login": "octocat"},
            "base": {"ref": "master"},
            "head": {"ref": "feat/orders"},
        },
        "changed_files": changed_files or [],
    }


def _signed_headers(payload_body: bytes, *, event: str = "pull_request") -> dict[str, str]:
    signature = hmac.new(WEBHOOK_SECRET.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-Hub-Signature-256": f"sha256={signature}",
    }


def _post_webhook(client: TestClient, payload: dict[str, Any], *, event: str = "pull_request") -> Any:
    payload_body = json.dumps(payload).encode("utf-8")
    return client.post("/webhook", content=payload_body, headers=_signed_headers(payload_body, event=event))


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_rejects_missing_signature(client: TestClient) -> None:
    payload_body = json.dumps(_payload("closed", merged=True)).encode("utf-8")

    response = client.post(
        "/webhook",
        content=payload_body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing signature"}


def test_webhook_rejects_invalid_signature(client: TestClient) -> None:
    payload_body = json.dumps(_payload("closed", merged=True)).encode("utf-8")

    response = client.post(
        "/webhook",
        content=payload_body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid signature"}


def test_webhook_ignores_non_pull_request_event(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_calls: list[Any] = []
    async def fake_pipeline(pr_context: Any) -> bool:
        pipeline_calls.append(pr_context)
        return True

    monkeypatch.setattr(main, "run_post_merge_pipeline", fake_pipeline)

    response = _post_webhook(
        client,
        _payload("closed", merged=True, changed_files=["backend/services/orders.py"]),
        event="push",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pipeline_calls == []


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened", "edited"])
def test_webhook_ignores_non_closed_pull_request_actions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    pipeline_calls: list[Any] = []
    async def fake_pipeline(pr_context: Any) -> bool:
        pipeline_calls.append(pr_context)
        return True

    monkeypatch.setattr(main, "run_post_merge_pipeline", fake_pipeline)

    response = _post_webhook(
        client,
        _payload(action, changed_files=["backend/services/orders.py"]),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pipeline_calls == []


def test_webhook_ignores_closed_unmerged_pull_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_calls: list[Any] = []
    async def fake_pipeline(pr_context: Any) -> bool:
        pipeline_calls.append(pr_context)
        return True

    monkeypatch.setattr(main, "run_post_merge_pipeline", fake_pipeline)

    response = _post_webhook(
        client,
        _payload("closed", merged=False, changed_files=["backend/services/orders.py"]),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pipeline_calls == []


def test_webhook_accepts_merged_backend_pull_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_calls: list[main.PullRequestContext] = []
    fetch_calls: list[tuple[str, int]] = []

    async def fake_pipeline(pr_context: main.PullRequestContext) -> bool:
        pipeline_calls.append(pr_context)
        return True

    async def fake_fetch_changed_files(repository: str, pr_number: int) -> list[str]:
        fetch_calls.append((repository, pr_number))
        return ["backend/services/foo.py"]

    monkeypatch.setattr(main, "fetch_pull_request_changed_files", fake_fetch_changed_files)
    monkeypatch.setattr(main, "run_post_merge_pipeline", fake_pipeline)

    response = _post_webhook(
        client,
        _payload("closed", merged=True, changed_files=[]),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert fetch_calls == [("owner/repo", 42)]
    assert pipeline_calls == [
        main.PullRequestContext(
            repository="owner/repo",
            pr_number=42,
            title="Add feature",
            merged_at="2026-06-03T17:00:00Z",
            author="octocat",
            changed_files=["backend/services/foo.py"],
            base_branch="master",
            head_branch="feat/orders",
            default_branch="main",
        )
    ]


def test_webhook_ignores_merged_frontend_pull_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_calls: list[main.PullRequestContext] = []

    async def fake_pipeline(pr_context: main.PullRequestContext) -> bool:
        pipeline_calls.append(pr_context)
        return False

    async def fake_fetch_changed_files(repository: str, pr_number: int) -> list[str]:
        return ["frontend/components/Button.tsx"]

    monkeypatch.setattr(main, "fetch_pull_request_changed_files", fake_fetch_changed_files)
    monkeypatch.setattr(main, "run_post_merge_pipeline", fake_pipeline)

    response = _post_webhook(
        client,
        _payload("closed", merged=True, changed_files=["backend/services/from-payload-is-ignored.py"]),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert len(pipeline_calls) == 1


@pytest.mark.parametrize(
    ("changed_files", "expected"),
    [
        (["api/orders.py"], True),
        (["routes/orders.py"], True),
        (["controllers/orders.py"], True),
        (["services/orders.py"], True),
        (["models/order.py"], True),
        (["schemas/order.py"], True),
        (["migrations/20260603_add_orders.sql"], True),
        (["backend/app.py"], True),
        (["frontend/components/Button.tsx"], False),
        ([], False),
    ],
)
def test_backend_relevance_detection(changed_files: list[str], expected: bool) -> None:
    assert is_backend_relevant_pr(changed_files) is expected

