from typing import Any

import pytest

from backend.features import self_reviewer


class FakeResponse:
    def __init__(self, payload: Any = None) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_self_review_posts_comment_when_no_existing_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("get", args[0]))
        return FakeResponse([])

    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("post", args[0]))
        return FakeResponse({})

    def fake_patch(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("patch", args[0]))
        return FakeResponse({})

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(self_reviewer.httpx, "get", fake_get)
    monkeypatch.setattr(self_reviewer.httpx, "post", fake_post)
    monkeypatch.setattr(self_reviewer.httpx, "patch", fake_patch)

    self_reviewer._upsert_pr_comment("owner/repo", 42, self_reviewer._format_review_comment([]))

    assert calls == [
        ("get", "https://api.github.com/repos/owner/repo/issues/42/comments"),
        ("post", "https://api.github.com/repos/owner/repo/issues/42/comments"),
    ]


def test_self_review_updates_existing_comment_to_prevent_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("get", args[0]))
        return FakeResponse([{"id": 99, "body": "## MergeFlow AI Self Review\n\nOld review"}])

    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("post", args[0]))
        return FakeResponse({})

    def fake_patch(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append(("patch", args[0]))
        return FakeResponse({})

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(self_reviewer.httpx, "get", fake_get)
    monkeypatch.setattr(self_reviewer.httpx, "post", fake_post)
    monkeypatch.setattr(self_reviewer.httpx, "patch", fake_patch)

    self_reviewer._upsert_pr_comment("owner/repo", 42, self_reviewer._format_review_comment([]))

    assert calls == [
        ("get", "https://api.github.com/repos/owner/repo/issues/42/comments"),
        ("patch", "https://api.github.com/repos/owner/repo/issues/comments/99"),
    ]
