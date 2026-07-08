"""SQLite-backed state: workflows, calls, events. Small on purpose."""
import os
import sqlite3
import threading
import time


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._conn as c:
            c.execute("""CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'active',
                budget_usd REAL NOT NULL,
                spent_usd REAL NOT NULL DEFAULT 0,
                calls INTEGER NOT NULL DEFAULT 0,
                warned INTEGER NOT NULL DEFAULT 0,
                downgraded INTEGER NOT NULL DEFAULT 0,
                killed_reason TEXT,
                created_at REAL NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS calls (
                ts REAL NOT NULL,
                workflow_id TEXT NOT NULL,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL,
                latency_ms INTEGER,
                prompt_hash TEXT
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS events (
                ts REAL NOT NULL,
                workflow_id TEXT,
                severity TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL
            )""")

    # -- workflows -----------------------------------------------------------
    def find_workflow(self, wf_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
        return dict(row) if row else None

    def calls_for(self, wf_id: str, limit: int = 500) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM calls WHERE workflow_id=? ORDER BY ts LIMIT ?",
                (wf_id, limit)).fetchall()]

    def events_for(self, wf_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM events WHERE workflow_id=? ORDER BY ts LIMIT ?",
                (wf_id, limit)).fetchall()]

    def get_or_create_workflow(self, wf_id: str, budget_usd: float) -> dict:
        with self._lock, self._conn as c:
            row = c.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO workflows (id, budget_usd, created_at) VALUES (?,?,?)",
                    (wf_id, budget_usd, time.time()),
                )
                row = c.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
            return dict(row)

    def update_workflow(self, wf_id: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn as c:
            c.execute(f"UPDATE workflows SET {cols} WHERE id=?", (*fields.values(), wf_id))

    def add_spend(self, wf_id: str, cost: float) -> float:
        with self._lock, self._conn as c:
            c.execute(
                "UPDATE workflows SET spent_usd = spent_usd + ?, calls = calls + 1 WHERE id=?",
                (cost, wf_id),
            )
            row = c.execute("SELECT spent_usd FROM workflows WHERE id=?", (wf_id,)).fetchone()
            return row["spent_usd"] if row else 0.0

    # -- calls / events ------------------------------------------------------
    def record_call(self, wf_id, model, pt, ct, cost, latency_ms, prompt_hash):
        with self._lock, self._conn as c:
            c.execute(
                "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), wf_id, model, pt, ct, cost, latency_ms, prompt_hash),
            )

    def add_event(self, wf_id, severity, etype, message):
        with self._lock, self._conn as c:
            c.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (time.time(), wf_id, severity, etype, message),
            )

    # -- dashboard snapshot ----------------------------------------------------
    def state(self) -> dict:
        with self._lock:
            wfs = [dict(r) for r in self._conn.execute(
                "SELECT * FROM workflows ORDER BY created_at DESC").fetchall()]
            events = [dict(r) for r in self._conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT 100").fetchall()]
            totals = dict(self._conn.execute(
                "SELECT COALESCE(SUM(spent_usd),0) AS spent, COALESCE(SUM(calls),0) AS calls "
                "FROM workflows").fetchone())
        return {"workflows": wfs, "events": events, "totals": totals}
