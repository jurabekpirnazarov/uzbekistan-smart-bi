"""MCP server (FastMCP). Tools are thin wrappers over app.services — no business logic here.

Run:
    python -m mcp_server.server                     # streamable-http on :8100 (path /mcp)
    python -m mcp_server.server --transport stdio   # for Claude Desktop / MCP Inspector over stdio
"""

from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import __version__
from app.services.health import get_health

mcp = FastMCP(
    "uz-smart-bi",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8100")),
)


@mcp.tool()
def ping() -> dict:
    """Check that the MCP server and its database are reachable."""
    health = get_health(__version__)
    return {"data": {"pong": True, "db": health.db}, "meta": {"version": __version__}, "warnings": []}


@mcp.custom_route("/health", methods=["GET"])
async def health_route(_: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics_route(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Uzbekistan Smart BI MCP server")
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
