# Vyber API — one image for local compose, EC2, and (later) ECS Fargate.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY core ./core
COPY api ./api
COPY skills ./skills
# Editable install on purpose: the code resolves the skills/ directory
# relative to the source tree, exactly as in local dev — one code path.
RUN pip install --no-cache-dir -e .

# All state (sqlite db, workspaces, traces) lives under /data — mount a
# host directory or volume there; the container itself is disposable.
ENV VYBER_DATA_DIR=/data
EXPOSE 8091
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/healthz')" || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8091"]
