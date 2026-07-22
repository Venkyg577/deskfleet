# DeskFleet: Project Rules

## What this is

A deployed multi-agent support-ticket resolver. A LangGraph crew of four nodes (Classifier, Researcher, Responder, Reviewer) resolves a ticket against an external order API and returns one terminal decision: RESOLVED, ESCALATE, or REFUSE.

Full spec: `docs/PRD.md`. Build order and gates: `docs/SESSION_PLAN.md`.

Read the PRD before writing code in any new module. The PRD is the source of truth. If code and PRD disagree, ask me which one is wrong.

## Hard constraints

This is a 2-day capstone build. Scope is locked. These are not preferences.

1. NEVER add a dependency without asking me first.
2. NEVER implement anything in PRD section 2.2 (out of scope). If a change feels like it needs Grafana, SSE streaming, Postgres, CrewAI, or semantic guardrails, stop and tell me instead of building it.
3. Every tool invocation goes through `app/tools/registry.py::execute_tool()`. No node calls a tool function directly. This is the allowlist enforcement point and a graded outcome.
4. `state["raw_ticket"]` is for the audit log only. It NEVER reaches a model. Nodes read `state["ticket"]` (sanitized).
5. All LLM calls use `temperature=0` and the model from `settings.LLM_MODEL`.
6. Tests must pass with NO network and NO API keys. `LLM_PROVIDER=fake` and `STORE_API_OFFLINE=1`. If a test needs a real key, the test is wrong.
7. Never invent an upstream API field. FakeStoreAPI has no order-status field. Status, ETA, and carrier come from `app/tools/fixtures/order_status.json`, joined to the live cart response. This is documented, deliberate, and must stay honest.
8. Never hardcode a token price without a source comment and a check date.

## Working style

- Stop at every phase gate in `docs/SESSION_PLAN.md`. Do not run ahead into the next phase. Report what you built and what I should verify.
- Prefer small files. If a file passes roughly 200 lines, tell me before splitting it.
- Write the test alongside the module, not at the end.
- When something in the PRD is ambiguous, ask one question. Do not guess and proceed.
- No speculative abstraction. No base classes, no plugin systems, no config layers beyond `config.py`. Two days.
- If you hit an error you cannot resolve in two attempts, stop and show me the error rather than working around it.

## Code conventions

- Python 3.11+, type hints everywhere
- Pydantic v2. Settings via `pydantic-settings` in `app/config.py`. Nothing reads `os.environ` directly except `config.py`.
- httpx for HTTP, 5 second timeout, one retry, fixture fallback on failure
- Structured logging via stdlib `logging`. Never log PII or raw ticket text.
- Prometheus collectors declared once in `app/metrics.py`, imported elsewhere

## Documentation style (README.md, BUILD_NOTE.md, code comments)

- No em dashes anywhere. Use commas, colons, or parentheses.
- Direct and concrete. No marketing language. No "seamlessly", "leverage", "robust", "powerful", "cutting-edge".
- Concrete numbers over vague claims. Say "4 tool calls max", not "bounded".
- Write like a person explaining to a colleague, not like a product page.

## Commands

```
Run locally:   uvicorn app.main:app --reload --port 8080
Tests:         LLM_PROVIDER=fake STORE_API_OFFLINE=1 pytest -q
One ticket:    python scripts/run_ticket.py "<ticket text>"
Docker build:  docker build -t deskfleet .
Docker run:    docker run -p 8080:8080 --env-file .env deskfleet
```

## Definition of done

Four artifacts: GitHub repo with README, 3 to 5 minute demo video, live Cloud Run URL, `BUILD_NOTE.md`. See PRD section 16 for the traceability checklist. Every row must tick before I submit.
