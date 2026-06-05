import pytest

from backend.classifier import diff_classifier


class FakeResponse:
    text = '{"change_types": ["API", "Authentication"], "summary": "Added login endpoint returning JWT token."}'


created_models: list[str] = []
client_api_versions: list[str] = []


class FakeModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> FakeResponse:
        created_models.append(model)
        return FakeResponse()


class FakeClient:
    def __init__(self, **kwargs: object) -> None:
        http_options = kwargs.get("http_options")
        api_version = getattr(http_options, "api_version", None)
        client_api_versions.append(str(api_version))

        self.models = FakeModels()


def test_classify_backend_diff_returns_structured_json(monkeypatch: pytest.MonkeyPatch) -> None:
    created_models.clear()
    client_api_versions.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_CLASSIFIER_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_CLASSIFIER_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_VERSION", raising=False)
    monkeypatch.setattr(diff_classifier.genai, "Client", FakeClient)

    classification = diff_classifier.classify_backend_diff(
        "diff --git a/backend/api/auth.py b/backend/api/auth.py",
        ["backend/api/auth.py"],
    )

    assert classification.change_types == ["API", "Authentication"]
    assert classification.summary == "Added login endpoint returning JWT token."
    assert created_models == ["gemini-2.5-flash-lite"]
    assert client_api_versions == ["v1beta"]


def test_classifier_model_and_api_version_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_CLASSIFIER_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_CLASSIFIER_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("GEMINI_API_VERSION", "v1beta")

    assert diff_classifier.get_classifier_model() == "gemini-2.5-flash"
    assert diff_classifier.get_classifier_fallback_model() == "gemini-2.5-flash-lite"
    assert diff_classifier.get_gemini_api_version() == "v1beta"
    assert diff_classifier.get_classifier_model_candidates() == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_classifier_tries_fallback_model_on_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    created_models.clear()

    class FailingThenSuccessModels:
        def generate_content(self, *, model: str, contents: str, config: object) -> FakeResponse:
            created_models.append(model)
            if model == "gemini-2.5-flash-lite":
                raise RuntimeError("404 models/gemini-2.5-flash-lite is not found for API version v1")
            return FakeResponse()

    class FakeClientWithFallback:
        def __init__(self, **kwargs: object) -> None:
            self.models = FailingThenSuccessModels()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_CLASSIFIER_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_CLASSIFIER_FALLBACK_MODEL", raising=False)
    monkeypatch.setattr(diff_classifier.genai, "Client", FakeClientWithFallback)

    classification = diff_classifier.classify_backend_diff(
        "diff --git a/backend/services/foo.py b/backend/services/foo.py",
        ["backend/services/foo.py"],
    )

    assert classification.change_types == ["API", "Authentication"]
    assert created_models == ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


def test_classify_backend_diff_returns_unknown_on_gemini_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    classification = diff_classifier.classify_backend_diff(
        "diff --git a/backend/services/foo.py b/backend/services/foo.py",
        ["backend/services/foo.py"],
    )

    assert classification.change_types == ["Unknown"]
    assert classification.summary == "Unable to classify backend change."
