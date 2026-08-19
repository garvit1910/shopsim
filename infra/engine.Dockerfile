# Engine API image (Phase 5.7 seed for the Phase-9 compose; build context = repo root).
FROM python:3.11-slim
WORKDIR /repo
COPY engine/pyproject.toml engine/uv.lock* /repo/engine/
COPY engine/shopsim /repo/engine/shopsim
RUN pip install --no-cache-dir /repo/engine
# fixtures + runs are volume-mounted by compose so state lives on the host
EXPOSE 8000
CMD ["python", "-m", "shopsim.runner", "serve", "--config", "/repo/fixtures/run-configs/scripted-run-1.json", "--port", "8000"]
