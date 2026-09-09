"""MCP integration package — servers and client.

MCP Servers expose application tools for consumption by external MCP clients.
MCP Client connects to external community MCP servers and discovers their tools.

Public API:
    sql_mcp       — FastMCP server for SQL tools.
    document_mcp  — FastMCP server for document tools.
    rag_mcp       — FastMCP server for RAG tools.
    mcp_client    — Client manager for external MCP servers.
"""

from app.mcp.client import MCPClientManager, mcp_client
from app.mcp.servers.document_server import document_mcp
from app.mcp.servers.rag_server import rag_mcp
from app.mcp.servers.sql_server import sql_mcp

__all__ = [
    "MCPClientManager",
    "document_mcp",
    "mcp_client",
    "rag_mcp",
    "sql_mcp",
]
