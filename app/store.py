import json
import logging
import sqlite3

from app.config import settings

log = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id          TEXT PRIMARY KEY,
                raw_ticket         TEXT,
                ticket             TEXT,
                category           TEXT,
                decision           TEXT,
                reply              TEXT,
                escalation_reason  TEXT,
                iterations         INTEGER,
                tokens_prompt      INTEGER,
                tokens_completion  INTEGER,
                cost_usd           REAL,
                latency_ms         INTEGER,
                langsmith_trace_url TEXT,
                created_at         TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id  TEXT REFERENCES tickets(ticket_id),
                name       TEXT,
                args       TEXT,
                ok         INTEGER,
                result     TEXT,
                error      TEXT,
                latency_ms INTEGER
            )
        """)
    log.info("SQLite ready at %s", settings.DB_PATH)


def save_ticket(
    ticket_id: str,
    raw_ticket: str,
    ticket: str,
    category: str,
    decision: str,
    reply: str,
    escalation_reason: str | None,
    iterations: int,
    tokens_prompt: int,
    tokens_completion: int,
    cost_usd: float,
    latency_ms: int,
    langsmith_trace_url: str | None,
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO tickets VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (
                ticket_id, raw_ticket, ticket, category, decision, reply,
                escalation_reason, iterations, tokens_prompt, tokens_completion,
                cost_usd, latency_ms, langsmith_trace_url,
            ),
        )


def save_tool_calls(ticket_id: str, tool_calls: list) -> None:
    with _conn() as conn:
        for tc in tool_calls:
            conn.execute(
                "INSERT INTO tool_calls (ticket_id,name,args,ok,result,error,latency_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    ticket_id,
                    tc["name"],
                    json.dumps(tc["args"]),
                    1 if tc["ok"] else 0,
                    json.dumps(tc["result"]) if tc["result"] is not None else None,
                    tc["error"],
                    tc["latency_ms"],
                ),
            )


def get_ticket(ticket_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            return None
        ticket = dict(row)

        tc_rows = conn.execute(
            "SELECT * FROM tool_calls WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
        tool_calls = []
        for r in tc_rows:
            tc = dict(r)
            tc["args"] = json.loads(tc["args"] or "{}")
            tc["result"] = json.loads(tc["result"]) if tc["result"] else None
            tool_calls.append(tc)
        ticket["tool_calls"] = tool_calls
        return ticket
