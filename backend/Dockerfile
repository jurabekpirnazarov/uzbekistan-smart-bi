# Build context: repository root. One image for the API and the batch worker.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/backend MLFLOW_DISABLE_AGENT_HINT=1
WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install ./backend typer "mcp>=1.9,<2" "mlflow-skinny>=2.14"

COPY backend/alembic.ini backend/alembic.ini
COPY backend/alembic backend/alembic
COPY pipelines pipelines
COPY ml ml
COPY rag rag
COPY monitoring/__init__.py monitoring/drift.py monitoring/
COPY data/reference data/reference
COPY docs docs
COPY tests/eval tests/eval
COPY manage.py manage.py

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
