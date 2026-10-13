# Build context: repository root (so pipelines/ and ml/ can be copied in later phases).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install ./backend

COPY backend/alembic.ini backend/alembic.ini
COPY backend/alembic backend/alembic
COPY pipelines pipelines
COPY manage.py manage.py

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
