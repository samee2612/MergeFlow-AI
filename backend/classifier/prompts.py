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
