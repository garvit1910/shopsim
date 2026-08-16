"""Thin Bolt transport for HydraDB v0.1.x.

Constraints this wraps (see /infra/README.md, all live-probed in Phase 0.2):
- one Cypher statement per request; multi-step ops are sequenced client-side
- bearer auth is the working scheme: neo4j.bearer_auth(token)
- a transient 'mutation engine' (50N42) rejection was observed once right
  after a restart and did not reproduce -> retry exactly once, then raise

Concurrency model: neo4j sync sessions are not thread-safe, so each worker
thread owns one long-lived session (thread-local). Canonical write order
(shopper_id, t, event_rank) is a *within-shopper* requirement — different
shoppers touch disjoint subgraphs (single admitted writer, constraint 8) —
so run_grouped() parallelizes across groups while keeping strict statement
order inside each group.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

import neo4j

from .config import HydraConfig

# (cypher, params) — the unit every write/read path speaks in.
Statement = tuple[str, dict]

_TRANSIENT_MARKERS = ("mutation engine", "50N42")


class HydraClient:
    def __init__(self, cfg: HydraConfig | None = None):
        self.cfg = cfg or HydraConfig.from_env()
        self._driver = neo4j.GraphDatabase.driver(
            self.cfg.bolt_uri, auth=neo4j.bearer_auth(self.cfg.token)
        )
        self._driver.verify_connectivity()
        self._local = threading.local()
        self._sessions: list[neo4j.Session] = []
        self._sessions_lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None

    # -- session handling ---------------------------------------------------

    def _session(self) -> neo4j.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = self._driver.session()
            self._local.session = sess
            with self._sessions_lock:
                self._sessions.append(sess)
        return sess

    def _drop_session(self) -> None:
        sess = getattr(self._local, "session", None)
        if sess is not None:
            self._local.session = None
            with self._sessions_lock:
                if sess in self._sessions:
                    self._sessions.remove(sess)
            try:
                sess.close()
            except Exception:
                pass

    def _execute(self, query: str, params: dict) -> list[dict]:
        sess = self._session()
        try:
            return [dict(r) for r in sess.run(query, **params)]
        except Exception as exc:
            if not any(m in str(exc) for m in _TRANSIENT_MARKERS):
                raise
            # transient mutation-engine hiccup: fresh session, one retry
            self._drop_session()
            sess = self._session()
            return [dict(r) for r in sess.run(query, **params)]

    # -- public API ---------------------------------------------------------

    def run(self, query: str, **params) -> list[dict]:
        """One statement, materialized rows."""
        return self._execute(query, params)

    def run_stmt(self, stmt: Statement) -> list[dict]:
        query, params = stmt
        return self._execute(query, params)

    def run_seq(self, stmts: Iterable[Statement]) -> list[list[dict]]:
        """Strictly ordered sequence on the calling thread's session."""
        return [self._execute(q, p) for q, p in stmts]

    def run_grouped(self, groups: dict[Any, list[Statement]]) -> dict[Any, list[list[dict]]]:
        """Each group's statements run strictly in order; groups run in
        parallel (cfg.workers threads, one session each)."""
        if not groups:
            return {}
        if len(groups) == 1:
            key, stmts = next(iter(groups.items()))
            return {key: self.run_seq(stmts)}
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.cfg.workers, thread_name_prefix="hydra"
            )
        futures = {k: self._pool.submit(self.run_seq, stmts) for k, stmts in groups.items()}
        return {k: fut.result() for k, fut in futures.items()}

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None
        with self._sessions_lock:
            for sess in self._sessions:
                try:
                    sess.close()
                except Exception:
                    pass
            self._sessions.clear()
        self._driver.close()

    def __enter__(self) -> "HydraClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
