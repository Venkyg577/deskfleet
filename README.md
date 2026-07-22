# DeskFleet

DeskFleet is a multi-agent support ticket resolver. A LangGraph crew of four nodes (Classifier, Researcher, Responder, Reviewer) resolves a customer support message against FakeStoreAPI and returns one of three terminal decisions: RESOLVED, ESCALATE, or REFUSE. The whole pipeline runs in under 10 seconds with a live LangSmith trace for every resolved ticket.

---

## Architecture

```
POST /resolve
      |
   scan_input()          <-- injection detection, PII redaction, order_id extraction
      |
   [REFUSE early exit if injection]
      |
   LangGraph state machine
      |
      +-- Classifier     reads: ticket           writes: category
      +-- Researcher     reads: ticket, category writes: facts, tool_calls  (max 4 tool calls)
      +-- Responder      reads: ticket, facts     writes: draft
      +-- Reviewer       reads: draft, facts      writes: review_verdict, review_issues
            |
            +-- approve -> grounding check -> RESOLVED / ESCALATE
            +-- revise  -> Responder again (max 2 iterations)
            +-- escalate -> ESCALATE
      |
   outbound PII scan on draft
      |
   SQLite persist + Prometheus metrics
      |
   ResolveResponse (JSON)
```

Every tool call (get_order_status, get_product, search_products) goes through `execute_tool()` in `app/tools/registry.py`. No node calls a tool directly. This is the allowlist enforcement point.

Order status, carrier, and ETA come from `app/tools/fixtures/order_status.json`, joined to the live FakeStoreAPI cart response. FakeStoreAPI has no order-status field; the fixture is a documented overlay, not fabricated upstream data.

---

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in OPENAI_API_KEY and LANGCHAIN_API_KEY (optional, for traces)

uvicorn app.main:app --reload --port 8080
# UI: http://localhost:8080
# Health: http://localhost:8080/health
# Metrics: http://localhost:8080/metrics
```

One-shot from the command line:

```bash
python scripts/run_ticket.py "Where is my order 5?"
```

---

## Tests

All tests run with no network and no API keys:

```bash
LLM_PROVIDER=fake STORE_API_OFFLINE=1 pytest -q
```

---

## Docker

```bash
docker build -t deskfleet .
docker run -p 8080:8080 --env-file .env deskfleet
```

---

## Deploy to Cloud Run

Replace `YOUR_PROJECT` and `YOUR_REGION` (e.g. `asia-south1`) throughout.

### Step 0: one-time setup

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

### Step 1: create secrets

```bash
echo -n "sk-..." | gcloud secrets create OPENAI_API_KEY \
  --data-file=- --replication-policy=automatic

echo -n "ls__..." | gcloud secrets create LANGCHAIN_API_KEY \
  --data-file=- --replication-policy=automatic
```

### Step 2: create Artifact Registry repo (once)

```bash
gcloud artifacts repositories create deskfleet \
  --repository-format=docker \
  --location=YOUR_REGION
```

### Step 3: build and push

```bash
IMAGE=YOUR_REGION-docker.pkg.dev/YOUR_PROJECT/deskfleet/deskfleet:latest

gcloud builds submit --tag $IMAGE
```

### Step 4: deploy

```bash
gcloud run deploy deskfleet \
  --image $IMAGE \
  --region YOUR_REGION \
  --platform managed \
  --allow-unauthenticated \
  --max-instances 1 \
  --set-env-vars LLM_PROVIDER=openai,LLM_MODEL=gpt-4o-mini,LANGCHAIN_TRACING_V2=true,LANGCHAIN_PROJECT=deskfleet,STORE_API_BASE=https://fakestoreapi.com,STORE_API_OFFLINE=0,MAX_ITERS=2,MAX_TOOL_CALLS=4,DB_PATH=/tmp/deskfleet.db \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest,LANGCHAIN_API_KEY=LANGCHAIN_API_KEY:latest
```

`--max-instances=1` is required: Prometheus counters are in-process and per-instance.

### Step 5: verify

```bash
SERVICE_URL=$(gcloud run services describe deskfleet \
  --region YOUR_REGION --format="value(status.url)")

curl -s $SERVICE_URL/health
curl -s -X POST $SERVICE_URL/resolve \
  -H 'content-type: application/json' \
  -d '{"ticket":"Where is my order 5?"}' | python3 -m json.tool
```

**Live deployment:** https://deskfleet-813357224637.asia-south1.run.app

---

## Redeploy after a code change

```bash
gcloud builds submit --tag $IMAGE
gcloud run deploy deskfleet --image $IMAGE --region YOUR_REGION
```

---

## Prometheus metrics (local only)

`GET /metrics` exposes all 8 collectors in Prometheus text format.
A Grafana compose stack is documented in PRD section 14 but not deployed (out of scope for this build).

---

## Known limitations

See `docs/PRD.md` section 15 for the full list. Key ones:

- Prometheus metrics are in-process: multi-instance deploys would require Pushgateway.
- SQLite `/tmp/deskfleet.db` is ephemeral on Cloud Run. Persisted records survive only within the instance lifetime.
- FakeStoreAPI is a public sandbox and can be slow or unavailable. The offline fixture fallback keeps tests deterministic.
- Token cost uses tiktoken pre-flight estimates, not API response usage_metadata.
