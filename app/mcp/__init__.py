"""MCP (Model Context Protocol) server for the Repo SaaS platform.

Exposes the document repository's core operations — search, retrieval,
verification, issuance, and revocation — as MCP tools so AI agents can
interact with the platform through a standard protocol.

Run with:  python -m app.mcp
"""

from app.mcp.server import build_server, run

__all__ = ["build_server", "run"]
