"""MCP Client for connecting to external community MCP servers.

Discovers tools from external MCP servers and converts them to LangChain
tools for use in the LangGraph agent system. Supports both stdio and
HTTP transports.

Configuration is loaded from the ``mcp_servers.json`` file specified
in settings.

Example ``mcp_servers.json``::

    {
        "servers": [
            {
                "name": "weather",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-weather"],
                "transport": "stdio"
            },
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/data"],
                "transport": "stdio"
            }
        ]
    }
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model

from app.config import settings

logger = structlog.get_logger(__name__)
MCP_DISCOVERY_TIMEOUT_SECONDS = 5.0


def _json_schema_python_type(schema: Any) -> Any:
    """Map the supported JSON Schema value types to Pydantic field types."""
    if not isinstance(schema, dict):
        return Any
    schema_type = schema.get("type")
    type_map = {"string": str, "integer": int, "number": float, "boolean": bool}
    if schema_type == "array":
        item_type = _json_schema_python_type(schema.get("items", {}))
        return list[item_type]
    if schema_type == "object":
        additional_properties = schema.get("additionalProperties")
        value_type = (
            _json_schema_python_type(additional_properties)
            if isinstance(additional_properties, dict)
            else Any
        )
        return dict[str, value_type]
    return type_map.get(schema_type, Any)


class _StdioConnection:
    """Holds the async context managers for a single stdio MCP server.

    Prevents the ``async with`` blocks from closing prematurely by storing
    the ``__aenter__`` results and only tearing down on explicit ``close()``.
    """

    def __init__(self) -> None:
        self._transport_ctx: Any = None
        self._session_ctx: Any = None
        self.session: Any = None
        self.read: Any = None
        self.write: Any = None

    async def connect(self, server_params: Any) -> Any:
        """Open the stdio transport and MCP session, keep them alive."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        # Open transport — store the context manager so it doesn't close
        self._transport_ctx = stdio_client(server_params)
        self.read, self.write = await self._transport_ctx.__aenter__()

        # Open session
        self._session_ctx = ClientSession(self.read, self.write)
        self.session = await self._session_ctx.__aenter__()

        await self.session.initialize()
        return self.session

    async def close(self) -> None:
        """Tear down session and transport in reverse order."""
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_ctx = None

        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None

        self.session = None


class MCPClientManager:
    """Manages connections to external MCP servers and tool discovery.

    Design decisions:
        - Reads server config from a JSON file at startup.
        - Creates LangChain StructuredTool wrappers for discovered MCP tools.
        - Supports both stdio and streamable-http transports.
        - Keeps MCP server connections alive for the app's lifetime so tools
          can be invoked after discovery (context managers held open).
        - Caches discovered tools to avoid repeated connections.
        - Handles server failures gracefully (logs and continues).
    """

    def __init__(self) -> None:
        self._discovered_tools: list[StructuredTool] = []
        self._server_configs: list[dict[str, Any]] = []
        self._connections: dict[str, _StdioConnection] = {}
        self._initialized = False

    def load_config(self) -> list[dict[str, Any]]:
        """Load MCP server configuration from the JSON file.

        Returns:
            List of server config dicts.
        """
        config_path = Path(settings.mcp_servers_config)
        if not config_path.exists():
            logger.info("mcp_config_not_found", path=str(config_path))
            return []

        try:
            with open(config_path) as f:
                data = json.load(f)
            servers = data.get("servers", [])
            logger.info("mcp_config_loaded", server_count=len(servers))
            return servers
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("mcp_config_load_failed", error=str(exc))
            return []

    async def discover_tools(self) -> list[StructuredTool]:
        """Connect to all configured MCP servers and discover their tools.

        Returns:
            List of LangChain-compatible tools from all external servers.
        """
        if self._initialized:
            return self._discovered_tools

        self._server_configs = self.load_config()
        if not self._server_configs:
            self._initialized = True
            return []

        tasks = [self._connect_and_discover(config) for config in self._server_configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for config, result in zip(self._server_configs, results):
            if isinstance(result, Exception):
                logger.error(
                    "mcp_server_discovery_failed",
                    server=config.get("name", "unknown"),
                    error=str(result),
                )
            elif result:
                self._discovered_tools.extend(result)
                logger.info(
                    "mcp_tools_discovered",
                    server=config.get("name", "unknown"),
                    tool_count=len(result),
                )

        self._initialized = True
        logger.info("mcp_discovery_complete", total_tools=len(self._discovered_tools))
        return self._discovered_tools

    async def _connect_and_discover(self, config: dict[str, Any]) -> list[StructuredTool]:
        """Connect to a single MCP server and discover its tools.

        Args:
            config: Server configuration dict with name, command, args, transport.

        Returns:
            List of LangChain tools discovered from this server.
        """
        transport = config.get("transport", "stdio")
        server_name = config.get("name", "unknown")

        if transport == "stdio":
            return await self._discover_stdio(config, server_name)
        else:
            logger.warning("unsupported_mcp_transport", transport=transport)
            return []

    async def _discover_stdio(
        self,
        config: dict[str, Any],
        server_name: str,
    ) -> list[StructuredTool]:
        """Connect to a stdio MCP server, keep the connection alive, and convert its tools.

        The connection is stored in ``self._connections`` so the session remains
        usable when tools are invoked later. It is torn down in ``close()``.

        Args:
            config: Server config with command and args.
            server_name: Logical name for logging.

        Returns:
            Converted LangChain tools.
        """
        from mcp import StdioServerParameters

        command = config.get("command", "")
        args = config.get("args", [])

        if not command:
            logger.warning("mcp_server_missing_command", server=server_name)
            return []

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=config.get("env"),
        )

        conn = _StdioConnection()
        try:
            async with asyncio.timeout(MCP_DISCOVERY_TIMEOUT_SECONDS):
                session = await conn.connect(server_params)
                mcp_tools = await session.list_tools()
                tools = [
                    self._convert_mcp_tool(mcp_tool, session, server_name)
                    for mcp_tool in mcp_tools.tools
                ]
        except BaseException:
            await conn.close()
            raise

        self._connections[server_name] = conn
        return tools

    def _convert_mcp_tool(
        self,
        mcp_tool: Any,
        session: Any,
        server_name: str,
    ) -> StructuredTool:
        """Convert an MCP tool to a LangChain StructuredTool.

        Creates an async wrapper that calls the MCP session's call_tool method.
        """
        tool_name = f"{server_name}_{mcp_tool.name}"
        description = mcp_tool.description or f"Tool from {server_name}"

        # Extract input schema from the MCP tool
        input_schema = mcp_tool.inputSchema if hasattr(mcp_tool, "inputSchema") else {}

        async def _call_tool(**kwargs: Any) -> str:
            """Invoke the MCP tool via the session."""
            try:
                result = await session.call_tool(mcp_tool.name, arguments=kwargs)
                # Extract text content from result
                if hasattr(result, "content") and result.content:
                    parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                    return "\n".join(parts) if parts else str(result)
                return str(result)
            except Exception as exc:
                logger.exception(
                    "mcp_tool_call_failed",
                    tool=tool_name,
                )
                return f"Tool error: {exc}"

        # Build a dynamic Pydantic model from the MCP input schema so that
        # LangChain's StructuredTool has the required ``args_schema``.
        fields: dict[str, Any] = {}
        props = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))
        for field_name, field_info in props.items():
            py_type = _json_schema_python_type(field_info)
            if field_name in required_fields:
                fields[field_name] = (py_type, ...)
            else:
                fields[field_name] = (py_type, None)

        args_model: type[BaseModel] = create_model(f"{tool_name}_Args", **fields)

        return StructuredTool(
            name=tool_name,
            description=description,
            func=None,  # Sync func not needed
            coroutine=_call_tool,
            args_schema=args_model,
        )

    async def get_tools(self) -> list[StructuredTool]:
        """Get all discovered external tools, discovering if not already done."""
        if not self._initialized:
            return await self.discover_tools()
        return self._discovered_tools

    async def get_tool_names(self) -> list[str]:
        """Get names of all discovered external tools."""
        tools = await self.get_tools()
        return [t.name for t in tools]

    async def close(self) -> None:
        """Close all MCP server connections gracefully."""
        for name, conn in self._connections.items():
            try:
                await conn.close()
                logger.debug("mcp_connection_closed", server=name)
            except Exception as exc:
                logger.warning("mcp_connection_close_failed", server=name, error=str(exc))

        self._connections.clear()
        self._discovered_tools.clear()
        self._initialized = False
        logger.info("mcp_client_closed")


# Module-level singleton
mcp_client = MCPClientManager()
