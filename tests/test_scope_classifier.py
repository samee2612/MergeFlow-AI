import pytest

from backend.classifier import scope_classifier


def test_marker_fallback_routes_backend_files_to_artifact_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_gemini(*args: object, **kwargs: object) -> scope_classifier.ChangeScopeClassification:
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr(scope_classifier, "_classify_with_gemini", fail_gemini)

    result = scope_classifier.classify_change_scope(
        ["backend/routes/payments.py"],
        pr_title="Add refund endpoint",
        repository="owner/repo",
    )

    assert result.action == "generate_api_artifacts"
    assert result.scope == "api"
    assert result.source == "marker_fallback"


def test_marker_fallback_routes_frontend_files_to_track_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_gemini(*args: object, **kwargs: object) -> scope_classifier.ChangeScopeClassification:
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr(scope_classifier, "_classify_with_gemini", fail_gemini)

    result = scope_classifier.classify_change_scope(
        ["frontend/components/Button.tsx"],
        pr_title="Update UI",
        repository="owner/repo",
    )

    assert result.action == "track_only"
    assert result.scope == "frontend"
    assert result.source == "marker_fallback"


def test_parse_scope_classification_json() -> None:
    result = scope_classifier._parse_scope_classification_json(
        """
        {
          "scope": "mixed",
          "action": "generate_api_artifacts",
          "change_types": ["API", "Frontend"],
          "summary": "Updates backend route and frontend page.",
          "confidence": "high"
        }
        """
    )

    assert result.scope == "mixed"
    assert result.action == "generate_api_artifacts"
    assert result.change_types == ["API", "Frontend"]
    assert result.confidence == "high"
    assert result.source == "gemini"


def test_classify_change_scope_uses_gemini_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_gemini(
        changed_files: list[str],
        pr_title: str,
        repository: str,
    ) -> scope_classifier.ChangeScopeClassification:
        return scope_classifier.ChangeScopeClassification(
            scope="frontend",
            action="track_only",
            summary="Frontend-only styling update.",
            change_types=["Frontend"],
            confidence="high",
            source="gemini",
        )

    monkeypatch.setattr(scope_classifier, "_classify_with_gemini", fake_gemini)

    result = scope_classifier.classify_change_scope(
        ["src/pages/Home.tsx"],
        pr_title="Restyle home page",
        repository="owner/repo",
    )

    assert result.action == "track_only"
    assert result.source == "gemini"
    assert result.summary == "Frontend-only styling update."
