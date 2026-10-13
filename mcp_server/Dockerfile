# Build context: repository root. Installs the backend package so tools can call app.services.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install ./backend "mcp>=1.9,<2"

COPY mcp_server mcp_server

EXPOSE 8100
HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8100/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "mcp_server.server"]
