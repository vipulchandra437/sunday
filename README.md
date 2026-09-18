# Sunday Agent

A private, local-first personal AI agent. Phase 1 provides the foundation infrastructure only: configuration, database schema, a model provider abstraction, a task state machine with checkpointing, a permission engine stub, and an audit service.

This project follows the specifications in `../Sunday_Documentation_Pack` (00_README through 09_RESEARCH_DECISION_LOG).

## Phase 1 scope

Included:
- FastAPI application skeleton with health/task/approval/audit endpoints
- SQLite database via SQLAlchemy + Alembic migrations
- Model provider interface with OpenRouter and Ollama implementations
- LangGraph task graph skeleton (CREATED → PLANNING → READY → EXECUTING → VERIFYING → COMPLETED, plus WAITING_FOR_APPROVAL / BLOCKED / FAILED / CANCELLED) with checkpoint persistence
- Permission engine stub: `ALLOW | DENY | REQUEST_APPROVAL | BLOCK`
- Audit service with secret redaction

Not built yet (by design):
- No tools (filesystem, shell, git, web, browser)
- No approval UI (backend stubs only)
- No email / calendar / job integrations
- No voice layer

## Project structure

```text
app/
├── main.py                          # FastAPI application
├── config/settings.py               # env settings + config.yaml loader
├── core/database.py                 # engine, session, Base
├── core/models.py                   # SQLAlchemy tables
├── core/security.py                 # risk levels + permission engine
├── services/model_provider.py       # provider interface + factory
├── services/providers/openrouter.py
├── services/providers/ollama.py
├── services/task_orchestrator.py    # state machine + LangGraph graph
├── services/audit_service.py        # sanitized audit logging
└── api/routes.py                    # REST endpoints
tests/
alembic/                             # migrations
.env.example
config.yaml
requirements.txt
README.md
```

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # optional; fill OPENROUTER_API_KEY to enable the OpenRouter provider
```

The app runs without `.env` using defaults (SQLite at `./sunday.db`).

## Database

```powershell
alembic upgrade head
```

## Run

```powershell
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive API documentation.

## Test

```powershell
pytest
```

## Security rules

- Secrets live only in environment variables or `.env` (gitignored). Never in source code.
- `credentials.access`, `security.policy_change`, `permission.policy_change`, and `approval.engine_modify` are blocked by default.
- The audit service redacts values whose keys contain hints such as `api`, `token`, `secret`, `password`, `authorization`, and `key` before persisting.
- The permission engine defaults to denying unknown tools (`deny_unknown_tools: true`).

## Task lifecycle

```text
CREATED -> PLANNING -> READY -> EXECUTING -> VERIFYING -> COMPLETED
                                            |-> FAILED
EXECUTING -> WAITING_FOR_APPROVAL -> EXECUTING | BLOCKED
any active state --cancel--> CANCELLED
```

State transitions are enforced by `TaskStateMachine` in `app/services/task_orchestrator.py`.