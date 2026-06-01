
MERGEFLOW AI
Product Design Document
The AI agent that handles everything after you merge a pull request

Version 1.0  |  1-Week Build  |  100% Free Tools  |  Open Source

 
Table of Contents

1.  Problem Statement	3
2.  What is MergeFlow AI	3
3.  Core Flow & Trigger Design	4
4.  Feature Specification	4
5.  Output Matrix	7
6.  Technology Stack	8
7.  System Architecture	9
8.  Folder Structure	10
9.  7-Day Build Timeline	11
10.  MCP Integration	12
11.  RAG Implementation	13
12.  Frontend Dashboard	13
13.  Deployment Guide	14
14.  Testing Strategy	15
15.  Resume & LinkedIn Story	15
 
1. Problem Statement
Every software team faces the same invisible tax after every merged PR. The code is done — but a developer still has to:
•	Manually move the Jira or GitHub ticket to 'Done'
•	Update API documentation or Swagger specs
•	Write QA test cases for the new functionality
•	Notify the team on Slack or email about the change
•	Update the Confluence or Notion workspace
•	Update the CHANGELOG

This work is repetitive, forgettable, and always slips. Docs rot. Tickets stay open for days. QA gets no guidance. The result is technical debt that compounds invisibly across every sprint.

	The core insight
Merging a PR is only 20% of the work. The remaining 80% — documentation, testing artifacts, notifications, ticket updates — is entirely manual today. MergeFlow automates that 80%.

2. What is MergeFlow AI
MergeFlow AI is an open-source, self-hostable AI agent that listens for GitHub pull request events and automatically triggers a post-merge pipeline. When a developer merges a PR with a specific GitHub label, MergeFlow:

•	Classifies the diff type (API, Frontend, Database, Mixed)
•	Moves the linked GitHub Issue to Done automatically
•	Generates QA test artifacts (Postman collection, Playwright scaffold, markdown plan)
•	Generates OpenAPI/Swagger spec and publishes a live Swagger UI page
•	Creates and updates Notion pages (API docs, QA plans, release log)
•	Runs a pre-merge self-review catching missing env vars, hardcoded values, leftover TODOs
•	Auto-updates CHANGELOG.md with a new dated entry
•	Sends a structured email summary via SendGrid with links to all artifacts
•	Visualizes the dependency graph of changed files across the codebase
 
3. Core Flow & Trigger Design
3.1 Trigger: GitHub PR Labels
MergeFlow uses GitHub PR Labels as the trigger mechanism — not branch name conventions, not commit message formats. Labels are native to GitHub, require zero developer tooling, and are a single click to apply when opening a PR.

Label	What it triggers	Use case
mergeflow: full	All features — QA + Docs + Notion + Email + Changelog	Complete feature PRs
mergeflow: qa-only	QA test artifacts only	Bug fixes with testable changes
mergeflow: docs-only	Swagger + Notion doc update only	API or schema changes
mergeflow: notify	Email summary + Changelog only	Minor changes worth communicating

3.2 Webhook Event Logic
The agent listens for GitHub webhook events with these exact conditions:

•	PR opened → triggers pre-merge self-review bot comment
•	PR merged (action: 'closed' AND pull_request.merged: true) → triggers post-merge pipeline based on label
•	PR closed without merge → no action taken

	Job Queue
GitHub webhooks have a 10-second response timeout. The webhook handler immediately returns 200 OK and pushes the job to a Celery + Redis queue. The pipeline runs asynchronously in a background worker. The dashboard receives real-time updates via WebSocket as each step completes.
 
4. Feature Specification
Feature 1: Pre-Merge Self Review
Trigger: PR opened event. The agent reads the diff and posts a structured review comment directly on the PR flagging:
•	Missing or undocumented environment variables added in the diff
•	Hardcoded values that should be moved to config (URLs, keys, magic numbers)
•	Leftover TODO / FIXME / console.log / print statements
•	Functions or endpoints added without corresponding tests

	Why this is real
Unlike AI code review tools that give general suggestions, this targets specific, verifiable issues that developers forget in every PR. The bot comment appears directly on GitHub — no context switching required.

Feature 2: GitHub Issue → Done
Trigger: PR merged. The agent extracts the linked issue number from:
1.	PR body keyword: 'Closes #123' or 'Fixes #123' (most reliable — parsed from webhook payload)
2.	Branch name regex: feat/123-add-login → extracts 123
3.	PR title regex: [#123] Add login flow → extracts 123

Once the issue number is found, the GitHub Projects API moves the card to the 'Done' column automatically. If no issue is linked, the step is skipped and logged.

Feature 3: Diff Type Classifier
The agent reads the list of changed files and classifies the PR into one or more of these categories. This determines which outputs are generated:

Detected type	Signal files	Outputs triggered
API	Route files, controllers, handlers, .yaml spec files	Postman Collection + OpenAPI spec + Swagger UI
Frontend	React/Vue/HTML/CSS components, pages	Playwright scaffold + UI test checklist
Database	Migration files, schema files, ORM models	Schema change notes in Notion
Infra/Config	.env, CI YAML, Dockerfile, config files	Env var PR comment + Notion update
Mixed	Combination of above	All relevant outputs combined

Feature 4: QA Test Artifacts
Based on diff type, the agent generates the following artifacts and commits them to /qa-docs/ in the repository:

4a. Postman Collection (API diffs)
•	Complete Postman Collection JSON ready to import — no manual setup
•	All new/modified endpoints with HTTP method, path, headers, sample request body
•	Role-based test cases (admin, standard user, guest) per endpoint
•	Staging and production environment variables pre-configured
•	Expected response status codes and schema

4b. Playwright Scaffold (Frontend diffs)
•	Correct file structure with describe/it blocks matching the changed components
•	Placeholder selectors with descriptive comments for QA to fill in
•	User flow tests covering the changed UI paths
•	Not fully runnable out of the box — requires selector fill-in (honest design decision)

4c. Markdown Test Plan (All diffs)
•	Plain English summary of what changed and what needs testing
•	Edge cases derived from the actual diff content
•	Role-based scenarios and environment-specific notes
•	Links to generated Postman collection and Playwright scaffold

Feature 5: OpenAPI / Swagger Spec + Live UI
For API diffs, the agent generates an OpenAPI 3.0 YAML spec for all new and modified endpoints. This is committed to /docs/api.yaml. GitHub Pages automatically renders a live Swagger UI at yourproject.github.io/docs — interactive, browseable, and testable by anyone on the team.

Feature 6: Notion Workspace Updates
MergeFlow maintains a structured Notion workspace per connected repository. On each merged PR, it creates or updates the following pages:

Notion Page	Triggered by	Content added
API Documentation	API diff	New/updated endpoints, request/response schemas
QA Test Plans	Any diff	Test plan summary + links to Postman/Playwright files
Release Log	Every merged PR	Dated entry with PR link, what changed, diff type
Feature README	Full feature label	Plain English feature summary for new team members

	Update behavior
The agent appends 'Updated in PR #123' sections rather than blindly rewriting existing content. Human-written documentation is preserved. Only new information is added. This is the correct production behavior.

Feature 7: CHANGELOG Auto-Update
After every merged PR with a MergeFlow label, the agent appends a new entry to CHANGELOG.md in the repository root. Format follows Keep a Changelog standard. The entry includes the date, PR number, author, and a one-line AI-generated summary of what changed. This is committed directly to the default branch.

Feature 8: Email Summary via SendGrid
SendGrid free tier (100 emails/day) sends a structured summary email to configured recipients after each pipeline run. The email intentionally does not duplicate documentation — it signals that work is done and links to everything:
•	Feature name and PR number
•	Change type detected (API / Frontend / Mixed)
•	Direct links to: Notion workspace, Swagger UI, QA test plan, Postman collection
•	One-paragraph AI-generated plain English summary of what the feature does

Feature 9: Env Variable Detector
On PR opened, the agent scans the diff for new environment variable references (os.getenv, process.env, etc.) that do not exist in .env.example. It posts a PR comment listing all new required variables and automatically creates a commit updating .env.example with the new keys (empty values). This prevents the most common deployment failure on small teams.

Feature 10: Dependency Graph Visualization
Using NetworkX (Python), the agent builds a dependency graph of the changed files — showing which modules import from the changed files and what the impact radius of the PR is. This graph is rendered in the frontend dashboard using React Flow. It gives developers and reviewers an immediate visual of how far-reaching a change is.
 
5. Output Matrix
Summary of all outputs generated per diff type:

Output	API	Frontend	Database	Infra	Mixed
Postman Collection JSON	✓	—	—	—	✓
OpenAPI / Swagger spec	✓	—	—	—	✓
Live Swagger UI (GitHub Pages)	✓	—	—	—	✓
Playwright test scaffold	—	✓	—	—	✓
Markdown QA test plan	✓	✓	✓	✓	✓
Notion API docs page updated	✓	—	—	—	✓
Notion QA test plan page	✓	✓	✓	✓	✓
Notion Release Log entry	✓	✓	✓	✓	✓
GitHub Issue moved to Done	✓	✓	✓	✓	✓
CHANGELOG.md updated	✓	✓	✓	✓	✓
SendGrid email summary	✓	✓	✓	✓	✓
Dependency graph (dashboard)	✓	✓	✓	✓	✓
Env var PR comment	✓	✓	✓	✓	✓
Pre-merge self review comment	✓	✓	✓	✓	✓
 
6. Technology Stack
All tools used are free tier or open source. No paid services required.

Layer	Technology	Purpose	Cost
Backend	Python 3.11 + FastAPI	Webhook listener, API, job orchestration	Free
AI Agent	Google Gemini API (gemini-2.5-pro)	Diff classification, QA generation, doc writing	Free tier
Agent Protocol	MCP (Model Context Protocol)	Tool calling interface for GitHub, Notion, SendGrid	Free / Open source
Job Queue	Celery + Redis	Async pipeline execution, webhook response < 200ms	Free (Railway)
RAG / Vector Store	ChromaDB + sentence-transformers	Context-aware generation from PR history	Free / Local
Graph Computation	NetworkX	Dependency graph from changed files	Free
Frontend	React + TypeScript + Vite	Real-time dashboard	Free
UI Deployment	Vercel	Frontend hosting	Free tier
Graph Visualization	React Flow	Interactive dependency graph in dashboard	Free
Real-time Updates	WebSockets (FastAPI)	Live pipeline status in dashboard	Free
Docs Platform	Notion API	QA plans, API docs, release log	Free tier
API Docs UI	Swagger UI (GitHub Pages)	Live interactive API documentation	Free
Email	SendGrid	Post-merge summary email	100/day free
Containerization	Docker + Docker Compose	One-command local setup	Free
Backend Deployment	Railway	Backend + Redis + Celery worker	Free tier
Logging	Loguru (structured JSON)	Observability and debugging	Free
 
7. System Architecture
7.1 High-Level Flow

Step	Component	Action
1	GitHub	PR opened/merged event fires webhook to MergeFlow backend
2	FastAPI Webhook Handler	Validates signature, returns 200 OK immediately, pushes job to Redis queue
3	Celery Worker	Picks up job, begins pipeline execution
4	Diff Classifier (Gemini via MCP)	Reads PR diff, classifies type (API/Frontend/DB/Infra/Mixed)
5	Feature Runners (parallel)	Each module runs based on classification + label
6	GitHub API (via MCP)	Issue moved to Done, .env.example updated, QA files committed
7	Notion API (via MCP)	Relevant pages created or updated
8	SendGrid (via MCP)	Summary email sent to configured recipients
9	WebSocket Broadcast	Each completed step broadcasts status to connected dashboard clients
10	React Dashboard	Pipeline run appears in real-time with all artifact links

7.2 MCP Architecture
MergeFlow exposes all external integrations as MCP (Model Context Protocol) servers. The Gemini agent calls tools through MCP rather than through hardcoded API clients. This makes integrations swappable and follows the emerging standard for AI agent tooling in 2026.

•	github-mcp-server: move_issue, create_pr_comment, commit_file, update_changelog
•	notion-mcp-server: create_page, append_to_page, update_page
•	sendgrid-mcp-server: send_email
•	chromadb-mcp-server: store_pr_context, retrieve_similar_prs

7.3 RAG Design
Every merged PR's diff, title, and generated outputs are embedded using sentence-transformers and stored in ChromaDB. When a new PR comes in, the agent retrieves the 3 most similar past PRs by semantic similarity. This context is injected into the Gemini prompt, enabling outputs like:
•	'This endpoint was also modified in PR #98. Here is what broke then.'
•	Consistent documentation style matching previous entries
•	Awareness of related features when generating QA edge cases
 
8. Folder Structure

mergeflow-ai/
├── backend/
│   ├── main.py                  # FastAPI app + webhook endpoint
│   ├── worker.py                # Celery worker entry point
│   ├── classifier/
│   │   └── diff_classifier.py   # Gemini-based diff type detection
│   ├── features/
│   │   ├── issue_mover.py       # GitHub Issue → Done
│   │   ├── qa_generator.py      # Postman + Playwright + Markdown
│   │   ├── swagger_generator.py # OpenAPI spec generation
│   │   ├── notion_updater.py    # Notion page management
│   │   ├── changelog_updater.py # CHANGELOG.md commits
│   │   ├── email_sender.py      # SendGrid email
│   │   ├── env_detector.py      # Env var PR comment
│   │   ├── self_reviewer.py     # Pre-merge review comment
│   │   └── graph_builder.py     # NetworkX dependency graph
│   ├── mcp_servers/
│   │   ├── github_mcp.py        # MCP server: GitHub tools
│   │   ├── notion_mcp.py        # MCP server: Notion tools
│   │   ├── sendgrid_mcp.py      # MCP server: Email tools
│   │   └── chromadb_mcp.py      # MCP server: RAG tools
│   ├── rag/
│   │   ├── embedder.py          # sentence-transformers embedding
│   │   └── retriever.py         # ChromaDB similarity search
│   └── websocket/
│       └── broadcaster.py       # WebSocket status updates
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── PipelineRun.tsx  # Single PR pipeline status
│   │   │   ├── DependencyGraph.tsx # React Flow graph
│   │   │   └── ArtifactLinks.tsx   # Links to outputs
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # Main dashboard
│   │   │   └── Settings.tsx     # Repo + integration config
│   │   └── hooks/
│   │       └── useWebSocket.ts  # Real-time pipeline updates
├── docker-compose.yml           # One-command local setup
├── .env.example                 # All required env variables
└── README.md                    # Setup + demo instructions
 
9. 7-Day Build Timeline
Each day has a clear deliverable. The goal is a deployed, working product by end of Day 7.

Day	Focus	Deliverable by end of day
Day 1	Foundation	FastAPI webhook listener running locally. GitHub webhook fires, event is received and logged. Celery + Redis queue set up. Docker Compose working with one command.
Day 2	Core pipeline	Diff classifier working via Gemini API. GitHub Issue moved to Done on merge. Env var detector posting PR comments. Pre-merge self review bot comment live.
Day 3	QA artifacts	Postman Collection generated and committed to repo for API diffs. Playwright scaffold generated for frontend diffs. Markdown test plan generated for all types.
Day 4	Docs + Notion	OpenAPI spec generated and Swagger UI live on GitHub Pages. Notion pages created and updated on merge. CHANGELOG.md auto-updated on each merge.
Day 5	MCP + RAG + Email	All integrations refactored to use MCP servers. ChromaDB storing PR embeddings. RAG context injected into Gemini prompts. SendGrid email sending on merge.
Day 6	Frontend dashboard	React dashboard deployed to Vercel. WebSocket real-time pipeline status working. Dependency graph visualized with React Flow. All artifact links displayed.
Day 7	Ship the story	README complete with architecture diagram and demo GIF. End-to-end test on a real repo. Railway deployment live. Medium article drafted. LinkedIn post written.

	Priority rule
Days 1-3 give you a working, deployable product. Days 4-6 make it impressive. Day 7 is what gets you the interview. If time runs short, cut Day 6 features before cutting Day 7.
 
10. MCP Integration
What is MCP
Model Context Protocol (MCP) is an open standard for connecting AI agents to external tools and data sources. It is the emerging standard for AI agent tooling in 2026. Every AI-first company is building with MCP. Having built production MCP servers is a strong resume signal.

How MergeFlow uses MCP
Instead of calling GitHub, Notion, and SendGrid APIs directly from Python, MergeFlow exposes each integration as an MCP server. The Gemini agent calls tools through the MCP protocol. This means:
•	Integrations are modular — swap Notion for Confluence by replacing one MCP server
•	The agent decides which tools to call based on the diff — not hardcoded conditionals
•	The architecture matches how production AI systems are built in 2026

MCP Server: GitHub

Tool name	Parameters	Action
move_issue_to_done	repo, issue_number	Moves GitHub Project card to Done column
create_pr_comment	repo, pr_number, body	Posts review comment on the PR
commit_file	repo, path, content, message	Commits a file to the repository
update_env_example	repo, new_vars[]	Appends new env vars to .env.example

MCP Server: Notion

Tool name	Parameters	Action
create_page	parent_id, title, content	Creates a new Notion page
append_to_page	page_id, content	Appends new block to existing page
find_page_by_title	database_id, title	Finds existing page to update
 
11. RAG Implementation
Why RAG in MergeFlow
Without RAG, every PR is processed in isolation — the agent has no memory of past changes. With RAG, the agent retrieves similar past PRs and uses that context to generate better, more consistent outputs.

Implementation
•	Embedding model: all-MiniLM-L6-v2 via sentence-transformers (free, runs locally)
•	Vector store: ChromaDB (free, local, no external service needed)
•	What gets embedded: PR title + description + diff summary + generated outputs
•	Retrieval: Top 3 most similar past PRs retrieved and injected into Gemini context

What RAG enables
•	Cross-PR awareness: 'This endpoint was also changed in PR #98, here is what failed in QA'
•	Consistent doc style: generated Notion pages match the format of previous entries
•	Better edge cases: QA plans reference failures from similar past changes
 
12. Frontend Dashboard
Pages
Dashboard (main)
•	List of all repos connected to MergeFlow
•	Each repo shows a feed of pipeline runs with status badges
•	Click any run to expand: step-by-step status, artifact links, timing
•	Real-time WebSocket updates — steps light up as they complete after a merge

Pipeline Detail View
•	Full pipeline run breakdown with timestamps per step
•	All generated artifact links: Postman collection, Playwright scaffold, Swagger UI, Notion pages
•	Dependency graph rendered with React Flow — shows impact radius of the PR
•	Self-review comment preview

Settings
•	Connect a GitHub repo (enter repo URL + personal access token)
•	Configure Notion workspace ID and API key
•	Configure SendGrid API key and recipient email list
•	Toggle individual features on/off per repo

Tech decisions
•	React + TypeScript + Vite: fast dev experience, strong typing
•	React Flow: dependency graph visualization
•	Native WebSocket (useWebSocket hook): real-time pipeline updates, no extra library
•	Vercel: free tier deployment, automatic on git push
 
13. Deployment Guide
Local Setup (Day 1 — do this first)
4.	Clone the repo and copy .env.example to .env
5.	Add your GitHub Personal Access Token, Notion API key, SendGrid API key, and Gemini API key to .env
6.	Run: docker-compose up — starts FastAPI, Redis, and Celery worker
7.	Run: ngrok http 8000 — get your public webhook URL
8.	Go to your GitHub repo → Settings → Webhooks → Add webhook
9.	Set payload URL to your ngrok URL + /webhook, content type application/json
10.	Select events: Pull requests
11.	Open a PR on your repo, add label 'mergeflow: full', merge it
12.	Watch the pipeline run in your terminal logs

Production Deployment
Backend (Railway — free tier)
•	Create a Railway project, connect your GitHub repo
•	Add Redis as a Railway plugin (free tier)
•	Set all environment variables in Railway dashboard
•	Railway auto-deploys on git push — Celery worker runs as a separate process

Frontend (Vercel — free tier)
•	Connect your GitHub repo to Vercel
•	Set VITE_BACKEND_URL environment variable to your Railway backend URL
•	Vercel auto-deploys frontend on git push

Swagger UI (GitHub Pages — free)
•	Enable GitHub Pages in your repo settings, set source to /docs folder
•	Agent commits openapi.yaml to /docs — Swagger UI renders automatically
 
14. Testing Strategy
What to test and how

Component	Test type	Tool	What to verify
Webhook handler	Unit	pytest	Correct events trigger pipeline, invalid events are ignored
Diff classifier	Unit	pytest + mock Gemini	API/Frontend/DB/Mixed classified correctly from sample diffs
Issue mover	Integration	pytest + GitHub test repo	Issue card moves to Done on merge
QA generator	Unit	pytest + mock Gemini	Postman JSON is valid and importable, Playwright scaffold has correct structure
Notion updater	Integration	pytest + Notion test workspace	Pages created and updated correctly
Email sender	Unit	pytest + SendGrid sandbox	Email sent with correct content and links
RAG retrieval	Unit	pytest + ChromaDB in-memory	Similar PRs retrieved correctly by embedding similarity
MCP servers	Unit	pytest	Each MCP tool returns expected response format
WebSocket	Integration	pytest + websockets client	Status broadcasts received by connected clients
End-to-end	Manual	Real GitHub repo	Full pipeline run on a real PR merge
 
15. Resume & LinkedIn Story
Resume bullet points
Use these on your resume under Projects:

•	Built MergeFlow AI — an open-source AI agent using Gemini API, MCP protocol, RAG (ChromaDB), and WebSockets that automates the entire post-merge developer workflow: ticket updates, QA test artifact generation (Postman collections, Playwright scaffolds), OpenAPI/Swagger doc publishing, Notion workspace updates, and team email summaries — triggered by GitHub webhooks with async job processing via Celery + Redis
•	Implemented MCP (Model Context Protocol) servers for GitHub, Notion, and SendGrid integrations — enabling modular, swappable AI tool calling following the 2026 industry standard for agent architectures
•	Built RAG pipeline using sentence-transformers and ChromaDB — injecting context from similar past PRs into generation prompts, improving QA plan quality and documentation consistency across PRs
•	Shipped React + TypeScript dashboard with real-time WebSocket pipeline status and interactive React Flow dependency graph visualization, deployed on Vercel

The interview story (30 seconds)

	Say this
At my last job I noticed that merging a PR was only 20% of the work. The remaining 80% — moving tickets, writing QA plans, updating docs, notifying the team — was entirely manual and always slipping. So I built MergeFlow: an AI agent that handles all of that automatically the moment a PR is merged. It classifies the diff type, generates the right QA artifacts, publishes live API docs, updates Notion, and sends an email summary. The whole thing uses MCP for tool calling, RAG for context-aware generation, and WebSockets for real-time status in a React dashboard.

LinkedIn post hook

	Opening line
I got tired of doing the same 6 manual tasks after every PR merge. So I built an agent to do them for me. Here's what MergeFlow AI does the moment you merge a PR [link to live demo]

MergeFlow AI — Design Document v1.0
Built with Gemini API · MCP · RAG · React · FastAPI · Celery · Redis · Notion · SendGrid
