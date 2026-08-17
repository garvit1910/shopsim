"""Read-only progress/results API (PLAN 3.1's progress endpoint).

Thin by design: all state lives in the run-directory files the loop writes;
this just serves them. The dashboard (Phase 5) points here at S1.
"""

from __future__ import annotations

import json
from pathlib import Path


def create_app(runs_dir: Path):
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="shopsim runner", version="0.1.0")
    runs_dir = Path(runs_dir)

    def _run_file(run_id: str, name: str) -> dict:
        path = runs_dir / run_id / name
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"{run_id}/{name} not found")
        return json.loads(path.read_text())

    @app.get("/runs")
    def list_runs() -> list[dict]:
        reg = runs_dir / "registry.json"
        if not reg.exists():
            return []
        return json.loads(reg.read_text())["runs"]

    @app.get("/runs/{run_id}/progress")
    def progress(run_id: str) -> dict:
        return _run_file(run_id, "progress.json")

    @app.get("/runs/{run_id}/results")
    def results(run_id: str) -> dict:
        return _run_file(run_id, "results.json")

    return app


def serve(root: Path, port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(Path(root) / "runs"), host="127.0.0.1", port=port)
