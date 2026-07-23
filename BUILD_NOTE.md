# DeskFleet: Build Note

## 1. What shipped

Eight core outcomes, all live and verified:

1. A four-node LangGraph StateGraph (Classifier, Researcher, Responder, Reviewer) with typed state, conditional routing, and a max-iteration guard.
2. Three JSON-schema tools (`get_order_status`, `get_product`, `search_products`) called against FakeStoreAPI, chained by the Researcher.
3. A bounded tool allowlist: every call passes through `execute_tool()`, off-allowlist names return `TOOL_NOT_ALLOWED`.
4. Regex injection detection and PII redaction, inbound (before the graph) and outbound (on the reply).
5. Three terminal decisions surfaced in the API response: RESOLVED, ESCALATE, REFUSE.
6. Full LangSmith tracing with per-node latency and every tool call visible in state.
7. Prometheus token and cost metrics, eight collectors at `/metrics`.
8. Docker, Cloud Run, and a GitHub Actions pipeline that runs 25 safety tests before it builds or deploys.

Live URL: https://deskfleet-813357224637.asia-south1.run.app
Repo: https://github.com/Venkyg577/deskfleet

What I care about most is that this system stays honest under pressure. Ask it a vague question and it escalates to a human instead of inventing an answer. Ask it something it cannot verify against the looked-up facts, and the grounding check catches it before the reply leaves the building. The tool allowlist is one function I can test, not a rule scattered across four nodes. Honesty and a single enforcement point were the two things I did not want to compromise on.

---

## 2. Key decisions (the three deviations from the brief)

### D1. Researcher uses bound tools with a manual bounded loop, not AgentExecutor.

The brief suggests `create_tool_calling_agent` / `AgentExecutor`. I bound the three tools to the model and wrote the dispatch loop in the node body instead, capped at 4 calls, every call routed through `execute_tool()`.

I wanted to see and cap everything the agent does. A prebuilt AgentExecutor is a black box: it decides internally when to call tools and when to stop, and I cannot prove it will not call a tool more times than I want or reach for one it should not touch. My version caps the loop at four calls and routes every single call through one `execute_tool()` function. The result is that every tool call is visible in graph state and passes one gate I can unit test. I traded a little convenience for the ability to audit the agent. On a system whose whole point is trust, that is the right trade.

### D2. Frontend is a single static HTML page served by FastAPI, not Streamlit.

The brief accepts "vanilla HTML+JS calling the endpoint with fetch" as an alternative. I took it.

Streamlit is a separate process and Cloud Run gives you one port per service. Running two processes behind one port is fiddly and buys nothing a reviewer can see. One `index.html` served by the same FastAPI backend is one container, one deploy, one thing that can break. This was a shipping decision, not a shortcut: fewer moving parts for the same visible result.

### D3. Order status comes from a documented fixture overlay, not an invented upstream field.

FakeStoreAPI has products and carts but no fulfilment-status field. `get_order_status` reads `order_status.json` for status, ETA, and carrier, and joins the live cart for user_id and items. The overlay is labelled a fixture in the code and the README.

FakeStoreAPI knows about products and carts but has no field for order status. That field does not exist upstream. I had two choices: let the model invent a status and pretend it came from the API, or keep a small file that clearly says this is our data and join it to the real cart. I chose the honest one. I would rather ship a labelled fixture than a convincing lie. Fabricating a status and calling it upstream data is exactly the sloppy AI behaviour this project is meant to argue against, so faking it would have defeated the reason for building it.

---

## 3. Out of scope (the cutline)

Stated deliberately, not shipped silently. These were cut to protect a two-day build:

- Grafana dashboards. `/metrics` is exposed and scrapeable; the compose stack is documented, not deployed.
- SSE streaming of the agent loop to the UI.
- CrewAI comparison variant.
- Self-correcting Researcher (Plan-Act-Reflect).
- Semantic (embedding-based) guardrails. Regex only.
- Escalation webhook handoff to a mock human queue.
- Postgres. SQLite only.
- Any UI beyond one static page.

The temptation was Grafana, because a dashboard looks impressive on camera. I stopped because the metrics are already exposed and scrapeable at `/metrics`, and a dashboard would have cost hours the two-day budget did not have for something the raw output already proves.

---

## 4. Known limitations

Honest, unedited:

1. **Fixture-backed order status.** Status, ETA, and carrier come from a local overlay joined to live cart data, because the upstream API has no fulfilment field. Marked in code and README.
2. **Regex-only guardrails.** A paraphrased injection outside the eight patterns passes the input scan. The allowlist and the grounding post-check are the second and third lines of defence, which is why refusal is not the only control.
3. **Ephemeral SQLite.** On Cloud Run the audit DB at `/tmp/deskfleet.db` is wiped on restart and scale-out. LangSmith holds the durable trace. Cloud SQL or a GCS-persisted file is the production answer and is not implemented.
4. **Per-instance metrics.** Prometheus counters live in process; more than one replica diverges. Pinned to one instance as a workaround.
5. **No Grafana.** Metrics are exposed but no dashboard is deployed. Local compose stack included and documented.
6. **Single-judge reviewer.** One LLM judge, no second opinion, so judge bias is unmeasured.
7. **No evaluation dataset.** Correctness is demonstrated on four hand-picked tickets, not measured across a corpus.
8. **Non-streaming loop.** The user waits for the full graph to complete.

On item 7 specifically: I tested four cases I chose by hand, which is a demonstration and not a measurement. The honest next step is a set of around 30 labelled tickets with expected decisions, run as a nightly CI job that produces a decision-accuracy number and an escalation rate. I know the gap is there and I know what I would build to close it. That is the difference between "it worked when I tried it" and "I measured it."

---

## 5. Traceability: brief requirement to implementation

Every row proven.

| Brief core outcome | Where it lives | Proven by |
|---|---|---|
| 4-node StateGraph, typed state, conditional routing, max-iteration guard | `graph/build.py`, `routing.py` | `test_loop_guard.py`, Ticket B in the video |
| JSON-schema tools against external order API, chained by Researcher | `tools/registry.py`, `store_api.py` | Ticket B tool calls in the trace |
| Bounded tool allowlist | `execute_tool()` | `test_allowlist.py` |
| Regex injection detection and PII redaction, inbound and outbound | `guardrails/` | `test_injection.py`, `test_pii.py`, Ticket D |
| Terminal decision surfaced in the API response | `/resolve` response `decision` field | All four demo tickets |
| Full LangSmith tracing, per-node latency and tool calls | tracing env config, `node_latency_ms` | Trace theater segment |
| Prometheus token-budget and cost metrics | `metrics.py`, `/metrics` | `/metrics` output in the video |
| Docker, Cloud Run, GitHub Actions running safety tests before build | `Dockerfile`, `deploy.yml` | Live URL, green Actions run |
