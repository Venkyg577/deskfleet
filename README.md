# DeskFleet

DeskFleet is a deployed multi-agent support ticket resolver. A LangGraph crew of four nodes (Classifier, Researcher, Responder, Reviewer) reads a customer support message, looks up the relevant order or product, and returns one of three terminal decisions: RESOLVED, ESCALATE, or REFUSE. Every resolved ticket carries a LangSmith trace, a token count, and a cost figure.

**Live:** https://deskfleet-813357224637.asia-south1.run.app
**Repo:** https://github.com/Venkyg577/deskfleet

---

## Architecture

```
POST /resolve
      |
   scan_input()          injection detection, PII redaction, order_id extraction
      |
   [REFUSE early exit if the ticket is a prompt injection: zero LLM calls]
      |
   LangGraph state machine
      |
      +-- Classifier     reads: ticket           writes: category (order|product|refund|other)
      +-- Researcher     reads: ticket, category  writes: facts, tool_calls   (4 tool calls max)
      +-- Responder      reads: ticket, facts     writes: draft reply
      +-- Reviewer       reads: draft, facts      writes: verdict, issues
            |
            +-- approve  -> deterministic grounding check -> RESOLVED (or ESCALATE if ungrounded)
            +-- revise   -> back to Responder            (2 iterations max, then ESCALATE)
            +-- escalate -> ESCALATE
      |
   outbound PII scan on the reply
      |
   SQLite persist + Prometheus metrics
      |
   JSON response (decision, reply, tool_calls, iterations, cost, trace URL)
```

Four nodes, three decisions, two guardrail layers (inbound and outbound), one tool chokepoint.

### The tool allowlist

Every tool call in the system passes through one function, `execute_tool()` in `app/tools/registry.py`. No node calls a tool directly. If a name is not in the three-entry allowlist (`get_order_status`, `get_product`, `search_products`), the call returns `TOOL_NOT_ALLOWED` and increments a guardrail counter. This is the single point where tool access is enforced and the single thing the allowlist test checks.

### Where order data comes from

The language model knows nothing about your orders. Order facts come from two sources, joined at lookup time:

- **A local fixture, `app/tools/fixtures/order_status.json`,** supplies status, carrier, ETA, and total. It is seeded with orders 1 through 5 plus order 99999 (a deliberate "not found" case).
- **FakeStoreAPI (live), `/carts/{id}`,** supplies user_id and the item list.

FakeStoreAPI has products and carts but no fulfilment-status field. Rather than invent one and pass it off as upstream data, `get_order_status` reads the fixture for status, ETA, and carrier, and joins the live cart for the rest. The overlay is a documented fixture, not pretend upstream data. See "Deviation D3" in `BUILD_NOTE.md`.

Only order IDs present in the fixture (1 to 5) return data. Any other ID, including 99999, resolves to "not found" and escalates. This is a bounded demo dataset; adding an order is one entry in the JSON file.

---

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in OPENAI_API_KEY. LANGCHAIN_API_KEY is optional (enables traces).

uvicorn app.main:app --reload --port 8080
```

- UI: http://localhost:8080
- Health: http://localhost:8080/health
- Metrics: http://localhost:8080/metrics

Run one ticket from the command line:

```bash
python scripts/run_ticket.py "Where is my order 5?"
```

---

## Tests

All 29 tests run with no network and no API keys. The fake LLM provider returns scripted responses and the store API reads fixtures.

```bash
LLM_PROVIDER=fake STORE_API_OFFLINE=1 pytest -q
```

The graded safety tests:

- `test_allowlist.py`: an off-allowlist tool returns `TOOL_NOT_ALLOWED`, the real function is never called, the block counter increments.
- `test_loop_guard.py`: a reviewer that always says "revise" still terminates at `MAX_ITERS` with an ESCALATE decision, wrapped in a timeout so a runaway loop fails rather than hangs.
- `test_injection.py`: an injection ticket is refused with zero LLM calls and zero tool calls.
- `test_eval_gate.py`: every labeled injection in the eval dataset is refused (the guardrail regression gate, see Evaluation below).

---

## Evaluation

`tests/eval/dataset.jsonl` is a labeled set of 30 tickets, each with an expected decision (RESOLVED / ESCALATE / REFUSE) and category, spread across all three paths and grounded in the real fixtures (orders 1 to 5, the not-found order, the 20 products, the return policy). `scripts/run_eval.py` runs each ticket through the same pipeline the API uses and scores predicted decisions against the labels.

```bash
# Full run, real model (needs OPENAI_API_KEY in .env). Store offline for reproducibility.
LLM_PROVIDER=openai STORE_API_OFFLINE=1 python scripts/run_eval.py --report tests/eval/report.json

# Guardrail subset, deterministic, no network or key. This is the CI gate.
LLM_PROVIDER=fake STORE_API_OFFLINE=1 python scripts/run_eval.py --subset refuse
```

Latest full run (gpt-4o-mini, store offline): decision accuracy 30/30 (100%), category accuracy 19/21 (90.5%), escalation rate 23.3%. The two category disagreements are on borderline escalations (a delivery-related human request labeled `other` but classified `order`); both still produced the correct decision.

The REFUSE subset short-circuits on the injection scan before any LLM call, so CI runs it on the fake provider with no secrets and gates the deploy: weaken an injection pattern and a labeled attack drops from REFUSE to RESOLVED, turning the gate red. The full-set accuracy number needs a real provider and is run by hand, not in CI. This is a small hand-authored smoke and regression set with deliberately unambiguous labels, not an adversarial or statistically representative benchmark.

---

## Docker

```bash
docker build -t deskfleet .
docker run -p 8080:8080 --env-file .env deskfleet
```

The image is `python:3.11-slim`, runs as a non-root user, and binds to `$PORT` (Cloud Run injects it, default 8080).

---

## Deploy to Cloud Run

Replace `YOUR_PROJECT` and `YOUR_REGION` (this deployment uses `deskfleet-202607` and `asia-south1`).

### One-time setup

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

### Store secrets (no key ever goes in a file)

```bash
echo -n "sk-..." | gcloud secrets create OPENAI_API_KEY \
  --data-file=- --replication-policy=automatic

echo -n "ls__..." | gcloud secrets create LANGCHAIN_API_KEY \
  --data-file=- --replication-policy=automatic
```

Grant the Cloud Run runtime service account read access to the secrets:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Create the image registry (once)

```bash
gcloud artifacts repositories create deskfleet \
  --repository-format=docker --location=YOUR_REGION
```

### Build, push, deploy

```bash
IMAGE=YOUR_REGION-docker.pkg.dev/YOUR_PROJECT/deskfleet/deskfleet:latest

gcloud builds submit --tag $IMAGE

gcloud run deploy deskfleet \
  --image $IMAGE \
  --region YOUR_REGION \
  --platform managed \
  --allow-unauthenticated \
  --max-instances 1 \
  --set-env-vars LLM_PROVIDER=openai,LLM_MODEL=gpt-4o-mini,LANGCHAIN_TRACING_V2=true,LANGCHAIN_PROJECT=deskfleet,STORE_API_BASE=https://fakestoreapi.com,STORE_API_OFFLINE=0,MAX_ITERS=2,MAX_TOOL_CALLS=4,DB_PATH=/tmp/deskfleet.db \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest,LANGCHAIN_API_KEY=LANGCHAIN_API_KEY:latest
```

`--max-instances 1` is required. Prometheus counters live in process, so a second instance would split the metrics.

### Verify

```bash
SERVICE_URL=$(gcloud run services describe deskfleet \
  --region YOUR_REGION --format="value(status.url)")

curl -s $SERVICE_URL/health
curl -s -X POST $SERVICE_URL/resolve \
  -H 'content-type: application/json' \
  -d '{"ticket":"Where is my order 5?"}' | python3 -m json.tool
```

---

## Continuous deployment

`.github/workflows/deploy.yml` runs two jobs on every push to `main`:

1. **test**: installs dependencies and runs pytest with `LLM_PROVIDER=fake` and `STORE_API_OFFLINE=1`. No secrets, no network.
2. **deploy**: runs only after test passes, authenticates to GCP with a service account key from repo secrets, builds the image with Docker, pushes to Artifact Registry, and deploys to Cloud Run.

A failing test blocks the deploy.

---

## Metrics

`GET /metrics` exposes eight Prometheus collectors in text format: ticket counts by decision and category, ticket and per-node latency, tool calls by outcome, guardrail blocks by type, tokens by kind, cumulative cost, and review iterations.

A local Prometheus and Grafana compose stack is documented but not deployed. The `/metrics` endpoint is scrapeable; the dashboard layer was cut as out of scope for a two-day build.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/resolve` | Resolve one ticket. Returns decision, reply, tool calls, cost, trace URL. REFUSE returns 200. |
| GET | `/health` | Liveness and provider check |
| GET | `/metrics` | Prometheus text format |
| GET | `/tickets/{id}` | Persisted ticket record plus its tool-call audit rows |
| GET | `/` | Static single-page UI |

---

## Configuration

All settings load through `app/config.py` (pydantic-settings). Nothing else reads the environment directly.

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | (none) | Required when `LLM_PROVIDER=openai` |
| `LLM_PROVIDER` | `openai` | `fake` for tests |
| `LLM_MODEL` | `gpt-4o-mini` | All calls use temperature 0 |
| `LANGCHAIN_TRACING_V2` | `false` | `true` enables LangSmith traces |
| `STORE_API_OFFLINE` | `false` | `1` forces fixture-only, no network |
| `MAX_ITERS` | `2` | Reviewer revision cap |
| `MAX_TOOL_CALLS` | `4` | Researcher tool-call cap |

---

## Known limitations

- Prometheus metrics are in-process, so the deploy is pinned to one instance. Multi-instance would need a Pushgateway.
- SQLite lives at `/tmp/deskfleet.db`, which is ephemeral on Cloud Run. Records survive only for the instance lifetime.
- Token cost uses tiktoken pre-flight estimates times a hardcoded price table, not the API response usage figures.
- Order data is a five-order fixture. It demonstrates the architecture, not a production catalog.
- Guardrails are regex-based, not semantic. A novel injection phrasing outside the eight patterns would pass the inbound scan.

See `BUILD_NOTE.md` for the full decision log and `docs/PRD.md` section 15 for the complete limitation list.
