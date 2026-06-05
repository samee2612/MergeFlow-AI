API_SPEC_GENERATOR_SYSTEM_PROMPT = (
    "You generate structured backend API analysis documents for MergeFlow. "
    "Use only the provided PR summary, classification, changed files, patches, "
    "and file contents. Do not invent unrelated endpoints or flows."
)

API_SPEC_GENERATOR_USER_PROMPT = """Generate a Markdown API analysis document for this merged backend PR.

The document must be human-readable and structured for later Swagger/OpenAPI conversion.

Required sections:
1. Change Summary
2. Endpoint(s) Detected
3. Directly Related Files Considered
4. API Specification Snapshot
   - method
   - path
   - parameters
   - request body
   - headers
   - auth
   - env vars
   - responses
5. Test Cases
6. Edge Cases
7. Regression Risks
8. Swagger/OpenAPI-Ready Notes

For each endpoint, include where available:
- endpoint name / operation name
- HTTP method
- path
- tags / feature area
- summary of what the endpoint does
- auth requirement
- path parameters
- query parameters
- headers required
- request body schema
- example request body
- env vars needed
- direct dependencies / related files
- response codes
- response body shape
- example successful response
- example error responses
- concrete test cases derived from the flow

Coverage should include where relevant:
- happy path
- missing required field
- invalid input
- unauthorized / forbidden
- not found
- conflict
- validation failure
- edge cases based on the actual flow

Rules:
- Use Markdown only.
- Use "Not detected from provided context" when information is unavailable.
- Do not scan or infer outside the provided direct files.
- Do not describe frontend/UI behavior.
- Keep endpoint sections easy to convert into OpenAPI later.

PR context:
Repository: {repository}
PR number: {pr_number}
Title: {title}
Classification: {classification}
Classification summary: {classification_summary}

Changed files:
{changed_files}

Directly related files considered:
{related_files}

Unified diff patches by file:
{patches}

File contents:
{file_contents}
"""
