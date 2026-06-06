BACKEND_CLASSIFIER_SYSTEM_PROMPT = (
    "You classify merged backend pull request diffs for MergeFlow. "
    "Return strict JSON only. Do not include markdown, comments, or extra text."
)

BACKEND_CLASSIFIER_USER_PROMPT = """Classify this backend pull request using only these categories:
- API
- Service Logic
- Database
- Authentication
- Validation
- Configuration
- Bug Fix
- Refactor

Return JSON in this exact shape:
{{
  "change_types": ["API"],
  "summary": "One concise sentence describing what changed."
}}

Rules:
- Include one or more change_types.
- Use only the allowed category names.
- Base the answer on the changed files and diff.
- Keep summary factual and concise.

Changed files:
{changed_files}

Diff:
{diff_text}
"""

SCOPE_CLASSIFIER_SYSTEM_PROMPT = (
    "You route merged pull requests for MergeFlow. "
    "Decide whether a PR should trigger backend/API artifact generation or be tracked only. "
    "Return strict JSON only. Do not include markdown, comments, or extra text."
)

SCOPE_CLASSIFIER_USER_PROMPT = """Decide whether this merged pull request should trigger backend/API artifact generation.

Repository: {repository}
PR title: {pr_title}

Changed files:
{changed_files}

Return JSON in this exact shape:
{{
  "scope": "api",
  "action": "generate_api_artifacts",
  "change_types": ["API", "Service Logic"],
  "summary": "One concise sentence describing what changed.",
  "confidence": "high"
}}

Allowed values:
- scope: "api", "frontend", "database", "infra", "mixed"
- action: "generate_api_artifacts" or "track_only"
- confidence: "high", "medium", "low"

Decision rules:
- Use action "generate_api_artifacts" when the PR likely changes backend/API behavior or contracts.
- Strong backend/API signals include changes to:
  - routes, routers, controllers, handlers, endpoints
  - services, business logic, middleware
  - API schemas, DTOs, request/response models used by APIs
  - auth/validation logic tied to backend requests
  - backend config that affects API behavior
- Use action "track_only" when the PR is clearly non-backend, such as:
  - frontend/UI-only changes
  - CSS, styling, component layout
  - docs-only, README-only, comments-only
  - CI, Docker, Terraform, GitHub Actions, deployment config
  - test-only changes that do not modify backend/API code
- If the PR mixes frontend and backend/API changes, use scope "mixed" and action "generate_api_artifacts".
- If the PR is database-only (migrations/schema) with no API/router/service changes, use scope "database" and action "track_only".
- If file paths are ambiguous, infer from file names, extensions, and PR title.
- Prefer "track_only" only when you are confident there is no backend/API impact.
- Keep summary factual and concise.
- Do not invent files or changes not implied by the title and file list.
"""
