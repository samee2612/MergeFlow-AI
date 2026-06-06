from backend.generators.mermaid_generator import extract_openapi_operations, generate_mermaid_diagrams


OPENAPI_YAML = """openapi: 3.0.3
info:
  title: Auth API
  version: 0.1.0
paths:
  /login:
    post:
      summary: Login user
      responses:
        '200':
          description: Successful response
"""


def test_generate_mermaid_diagrams_uses_primary_openapi_endpoint() -> None:
    diagrams = generate_mermaid_diagrams(
        "Authentication Service",
        OPENAPI_YAML,
        "Validate credentials and issue JWT token.",
    )

    assert "flowchart TD" in diagrams.flowchart
    assert "POST /login" in diagrams.flowchart
    assert "sequenceDiagram" in diagrams.sequence_diagram
    assert "Client->>AuthenticationServiceAPI: POST /login" in diagrams.sequence_diagram


def test_extract_openapi_operations() -> None:
    operations = extract_openapi_operations(OPENAPI_YAML)

    assert operations == [
        {
            "method": "POST",
            "path": "/login",
            "summary": "Login user",
        }
    ]
