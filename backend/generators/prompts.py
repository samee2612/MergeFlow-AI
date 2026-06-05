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


OPENAPI_GENERATOR_SYSTEM_PROMPT = (
    "You generate valid OpenAPI 3.0 YAML for MergeFlow. "
    "Use the provided structured API analysis as the source of truth. "
    "Do not invent unrelated endpoints, integrations, or frontend behavior."
)

OPENAPI_GENERATOR_USER_PROMPT = """Generate a valid OpenAPI 3.0.3 YAML document for this merged backend PR.

Use the Step 3 structured API analysis below as the main source of truth. Include only endpoints and details supported by the analysis.

OpenAPI requirements:
- openapi: 3.0.3
- info.title
- info.version
- info.description
- paths
- operation summary
- operation tags
- auth/security requirements if detected
- path/query/header parameters if detected
- requestBody schema if detected
- example request bodies if detected
- response status codes
- response body schemas if detected
- example responses if detected
- environment variables under an x-mergeflow-env-vars extension if relevant

Rules:
- Return YAML only, with no Markdown fences or explanation.
- Use "Not detected from Step 3 analysis" only in description fields, not as fake schema names.
- Use empty objects where valid OpenAPI permits them if details are missing.
- If no endpoint is detected, return a minimal valid OpenAPI document with paths: {{}}.
- Keep the file readable in GitHub and reusable for future Postman generation.

PR context:
Repository: {repository}
PR number: {pr_number}
Title: {title}
Classification: {classification}
Classification summary: {classification_summary}

Step 3 structured API analysis:
{api_analysis_markdown}
"""


POSTMAN_GENERATOR_SYSTEM_PROMPT = (
    "You generate valid Postman Collection v2.1 JSON for MergeFlow. "
    "Use the provided OpenAPI YAML as the source of truth. "
    "Do not invent unrelated endpoints, integrations, or frontend behavior."
)

POSTMAN_GENERATOR_USER_PROMPT = """Generate a valid Postman Collection v2.1 JSON document from this OpenAPI YAML.

Use the OpenAPI document as the source of truth. Convert each operation under paths into one Postman request item.

Collection requirements:
- info.name
- info.schema: https://schema.getpostman.com/json/collection/v2.1.0/collection.json
- item array with one request per OpenAPI operation
- request name from operationId, summary, or METHOD path
- method
- URL using {{base_url}} plus the OpenAPI path
- query/path/header parameters with example values when available
- auth configuration when OpenAPI security is present
- request body with example JSON when available
- tests that check the response code is one of the documented response codes

Rules:
- Return JSON only, with no Markdown fences or explanation.
- Keep the file readable and importable into Postman.
- Use {{base_url}} for the server host.
- If no endpoint is present, return a minimal valid Postman collection with an empty item array.
- Preserve useful endpoint details from OpenAPI descriptions, examples, schemas, responses, and auth.

PR context:
Repository: {repository}
PR number: {pr_number}
Title: {title}

OpenAPI YAML:
{openapi_yaml}
"""
