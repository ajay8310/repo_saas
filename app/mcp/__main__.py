"""Module entry point: ``python -m app.mcp`` starts the MCP server over stdio."""

from app.mcp.server import run

if __name__ == "__main__":
    run()
