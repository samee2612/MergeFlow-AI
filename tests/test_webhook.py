import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.main as main


WEBHOOK_SECRET = "test-secret"


@pytest.fixture(autouse=True)
def configure_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _payload(action: str, *, merged: bool = False, labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "body": "Closes #123",
            "merged": merged,
            "labels": [{"name": label} for label in (labels or [])],
            "diff_url": "https://example.com/pr.diff",
            "head": {"ref": "feat/123-add-feature"},
            "user": {"login": "octocat"},
        },
    }


def _signed_headers(payload_body: bytes) -> dict[str, str]:
    signature = hmac.new(WEBHOOK_SECRET.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": f"sha256={signature}",
    }


def _post_webhook(client: TestClient, payload: dict[str, Any]) -> Any:
    payload_body = json.dumps(payload).encode("utf-8")
    return client.post("/webhook", content=payload_body, headers=_signed_headers(payload_body))


def _stub_pre_merge(
    monkeypatch: pytest.MonkeyPatch,
    *,
    diff_text: str = "diff --git a/app.py b/app.py\n+print('hello')",
) -> list[tuple[str, int, str]]:
    calls: list[tuple[str, int, str]] = []

    async def fake_fetch_pr_diff(diff_url: str) -> str:
        return diff_text

    def fake_delay(repo: str, pr_number: int, fetched_diff: str) -> None:
        calls.append((repo, pr_number, fetched_diff))

    monkeypatch.setattr(main, "fetch_pr_diff", fake_fetch_pr_diff)
    monkeypatch.setattr(main.run_pre_merge_review, "delay", fake_delay)
    return calls


def _stub_post_merge(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def fake_delay(*args: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(main.run_pipeline, "delay", fake_delay)
    return calls


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
def test_pre_merge_review_runs_for_pr_activity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    post_merge_calls = _stub_post_merge(monkeypatch)

    response = _post_webhook(client, _payload(action))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert pre_merge_calls == [("owner/repo", 42, "diff --git a/app.py b/app.py\n+print('hello')")]
    assert post_merge_calls == []


def test_pre_merge_review_runs_for_body_edit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    payload = _payload("edited")
    payload["changes"] = {"body": {"from": "old body"}}

    response = _post_webhook(client, payload)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert len(pre_merge_calls) == 1


def test_pre_merge_review_ignores_title_only_edit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    payload = _payload("edited")
    payload["changes"] = {"title": {"from": "Old title"}}

    response = _post_webhook(client, payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pre_merge_calls == []


def test_pre_merge_review_ignores_unchanged_body_edit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    payload = _payload("edited")
    payload["pull_request"]["body"] = "same body"
    payload["changes"] = {"body": {"from": "same body"}}

    response = _post_webhook(client, payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pre_merge_calls == []


def test_closed_merged_does_not_run_pre_merge_review(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    post_merge_calls = _stub_post_merge(monkeypatch)

    response = _post_webhook(client, _payload("closed", merged=True, labels=["mergeflow: full"]))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert pre_merge_calls == []
    assert len(post_merge_calls) == 1


def test_post_merge_still_requires_mergeflow_label(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch)
    post_merge_calls = _stub_post_merge(monkeypatch)

    response = _post_webhook(client, _payload("closed", merged=True))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pre_merge_calls == []
    assert post_merge_calls == []


def test_pre_merge_review_skips_empty_diff(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pre_merge_calls = _stub_pre_merge(monkeypatch, diff_text="   \n")

    response = _post_webhook(client, _payload("opened"))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert pre_merge_calls == []
