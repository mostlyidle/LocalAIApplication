"""Tests for MCP client manager — tool discovery, config loading, and conversions.

Targets app/mcp/client.py for 0% → 80%+ coverage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from app.mcp.client import MCPClientManager


# =============================================================================
# Config loading
# =============================================================================


class TestLoadConfig:
    """Tests for MCPClientManager.load_config()."""

    def test_returns_empty_when_file_not_found(self, tmp_path: Path):
        """When mcp_servers.json does not exist, return empty list."""
        manager = MCPClientManager()
        with patch("app.mcp.client.settings") as mock_settings:
            mock_settings.mcp_servers_config = str(tmp_path / "nonexistent.json")
            result = manager.load_config()
        assert result == []

    def test_returns_servers_from_valid_json(self, tmp_path: Path):
        """Valid config file should return the servers list."""
        config = {
            "servers": [
                {"name": "weather", "command": "npx", "args": ["-y", "server-weather"]},
                {"name": "fs", "command": "npx", "args": ["-y", "server-fs"]},
            ]
        }
        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(json.dumps(config))

        manager = MCPClientManager()
        with patch("app.mcp.client.settings") as mock_settings:
            mock_settings.mcp_servers_config = str(config_path)
            result = manager.load_config()

        assert len(result) == 2
        assert result[0]["name"] == "weather"
        assert result[1]["name"] == "fs"

    def test_returns_empty_on_invalid_json(self, tmp_path: Path):
        """Malformed JSON should not crash — returns empty list."""
        config_path = tmp_path / "bad.json"
        config_path.write_text("{broken json///")

        manager = MCPClientManager()
        with patch("app.mcp.client.settings") as mock_settings:
            mock_settings.mcp_servers_config = str(config_path)
            result = manager.load_config()
        assert result == []

    def test_returns_empty_on_missing_servers_key(self, tmp_path: Path):
        """JSON without 'servers' key should return empty."""
        config_path = tmp_path / "empty.json"
        config_path.write_text(json.dumps({"version": 1}))

        manager = MCPClientManager()
        with patch("app.mcp.client.settings") as mock_settings:
            mock_settings.mcp_servers_config = str(config_path)
            result = manager.load_config()
        assert result == []

    def test_handles_os_error(self, tmp_path: Path):
        """OSError (e.g. permission denied) should return empty, not crash."""
        config_path = tmp_path / "noperm.json"
        config_path.write_text(json.dumps({"servers": []}))
        config_path.chmod(0o000)

        manager = MCPClientManager()
        try:
            with patch("app.mcp.client.settings") as mock_settings:
                mock_settings.mcp_servers_config = str(config_path)
                result = manager.load_config()
            assert result == []
        finally:
            config_path.chmod(0o644)


# =============================================================================
# Tool discovery
# =============================================================================


class TestDiscoverTools:
    """Tests for MCPClientManager.discover_tools()."""

    async def test_returns_empty_when_no_config(self):
        """No config file → empty tools, marks as initialized."""
        manager = MCPClientManager()
        with patch.object(manager, "load_config", return_value=[]):
            result = await manager.discover_tools()
        assert result == []
        assert manager._initialized is True

    async def test_cached_after_first_call(self):
        """Second call returns cached tools without re-loading config."""
        manager = MCPClientManager()
        with patch.object(manager, "load_config", return_value=[]) as mock_load:
            await manager.discover_tools()
            await manager.discover_tools()
        # load_config should only be called once
        mock_load.assert_called_once()

    async def test_handles_server_connection_failure(self):
        """If a server connection raises, it should log and continue."""
        manager = MCPClientManager()
        config = [{"name": "bad-server", "command": "nonexistent", "transport": "stdio"}]

        with patch.object(manager, "load_config", return_value=config):
            with patch.object(
                manager,
                "_connect_and_discover",
                side_effect=ConnectionError("fail"),
            ):
                result = await manager.discover_tools()

        assert result == []
        assert manager._initialized is True

    async def test_collects_tools_from_multiple_servers(self):
        """Tools from multiple servers are collected into one list."""
        manager = MCPClientManager()
        configs = [
            {"name": "server1", "command": "cmd1"},
            {"name": "server2", "command": "cmd2"},
        ]
        tool1 = MagicMock(spec=StructuredTool)
        tool2 = MagicMock(spec=StructuredTool)
        tool3 = MagicMock(spec=StructuredTool)

        async def mock_discover(config: dict) -> list:
            if config["name"] == "server1":
                return [tool1, tool2]
            return [tool3]

        with patch.object(manager, "load_config", return_value=configs):
            with patch.object(manager, "_connect_and_discover", side_effect=mock_discover):
                result = await manager.discover_tools()

        assert len(result) == 3

    async def test_partial_failure_still_collects_good_tools(self):
        """If one server fails, tools from others are still collected."""
        manager = MCPClientManager()
        configs = [
            {"name": "good", "command": "cmd1"},
            {"name": "bad", "command": "cmd2"},
        ]
        good_tool = MagicMock(spec=StructuredTool)

        async def mock_discover(config: dict) -> list:
            if config["name"] == "bad":
                raise RuntimeError("server crashed")
            return [good_tool]

        with patch.object(manager, "load_config", return_value=configs):
            with patch.object(manager, "_connect_and_discover", side_effect=mock_discover):
                result = await manager.discover_tools()

        assert len(result) == 1


# =============================================================================
# _connect_and_discover routing
# =============================================================================


class TestConnectAndDiscover:
    """Tests for transport routing in _connect_and_discover."""

    async def test_stdio_transport(self):
        """stdio transport should call _discover_stdio."""
        manager = MCPClientManager()
        config = {"name": "test", "command": "echo", "transport": "stdio"}

        with patch.object(manager, "_discover_stdio", new_callable=AsyncMock, return_value=[]):
            result = await manager._connect_and_discover(config)
        assert result == []

    async def test_unsupported_transport_returns_empty(self):
        """Unsupported transport should return empty list."""
        manager = MCPClientManager()
        config = {"name": "test", "command": "echo", "transport": "grpc"}
        result = await manager._connect_and_discover(config)
        assert result == []

    async def test_default_transport_is_stdio(self):
        """No transport key should default to stdio."""
        manager = MCPClientManager()
        config = {"name": "test", "command": "echo"}

        with patch.object(manager, "_discover_stdio", new_callable=AsyncMock, return_value=[]):
            result = await manager._connect_and_discover(config)
        assert result == []


# =============================================================================
# _discover_stdio
# =============================================================================


class TestDiscoverStdio:
    """Tests for _discover_stdio."""

    async def test_returns_empty_when_command_missing(self):
        """Missing command key returns empty list."""
        manager = MCPClientManager()
        config = {"name": "test", "args": []}
        result = await manager._discover_stdio(config, "test")
        assert result == []


# =============================================================================
# _convert_mcp_tool
# =============================================================================


class TestConvertMcpTool:
    """Tests for _convert_mcp_tool — converting MCP tools to LangChain tools."""

    def test_creates_structured_tool_with_name_and_description(self):
        """Converted tool should have the expected name and description."""
        manager = MCPClientManager()
        mcp_tool = MagicMock()
        mcp_tool.name = "get_weather"
        mcp_tool.description = "Get weather for a location"
        mcp_tool.inputSchema = {"properties": {"city": {"type": "string"}}}

        session = AsyncMock()
        result = manager._convert_mcp_tool(mcp_tool, session, "weather")

        assert isinstance(result, StructuredTool)
        assert result.name == "weather_get_weather"
        assert result.description == "Get weather for a location"

    def test_uses_fallback_description(self):
        """If mcp_tool has no description, use fallback."""
        manager = MCPClientManager()
        mcp_tool = MagicMock()
        mcp_tool.name = "mystery"
        mcp_tool.description = None
        mcp_tool.inputSchema = {}

        session = AsyncMock()
        result = manager._convert_mcp_tool(mcp_tool, session, "srv")

        assert result.description == "Tool from srv"

    def test_handles_missing_input_schema(self):
        """If mcp_tool has no inputSchema attr, should still work."""
        manager = MCPClientManager()
        mcp_tool = MagicMock(spec=[])  # no attributes
        mcp_tool.name = "simple"
        mcp_tool.description = "A simple tool"

        session = AsyncMock()
        result = manager._convert_mcp_tool(mcp_tool, session, "srv")
        assert isinstance(result, StructuredTool)


# =============================================================================
# get_tools and get_tool_names
# =============================================================================


class TestGetToolsAndNames:
    """Tests for get_tools() and get_tool_names() convenience methods."""

    async def test_get_tools_triggers_discovery(self):
        """get_tools() should call discover_tools() if not initialized."""
        manager = MCPClientManager()
        with patch.object(manager, "discover_tools", new_callable=AsyncMock, return_value=[]):
            result = await manager.get_tools()
        assert result == []

    async def test_get_tools_skips_discovery_if_initialized(self):
        """get_tools() should return cached tools if already initialized."""
        manager = MCPClientManager()
        manager._initialized = True
        tool = MagicMock(spec=StructuredTool)
        manager._discovered_tools = [tool]
        result = await manager.get_tools()
        assert len(result) == 1

    async def test_get_tool_names(self):
        """get_tool_names() should return list of tool name strings."""
        manager = MCPClientManager()
        manager._initialized = True
        tool1 = MagicMock(spec=StructuredTool)
        tool1.name = "weather_get"
        tool2 = MagicMock(spec=StructuredTool)
        tool2.name = "fs_read"
        manager._discovered_tools = [tool1, tool2]

        result = await manager.get_tool_names()
        assert result == ["weather_get", "fs_read"]


# =============================================================================
# _call_tool closure (inside _convert_mcp_tool)
# =============================================================================


class TestConvertedToolInvocation:
    """Tests for the _call_tool closure created by _convert_mcp_tool."""

    async def test_call_tool_success(self):
        """Invoking a converted tool should call session.call_tool and extract text."""
        manager = MCPClientManager()
        mcp_tool = MagicMock()
        mcp_tool.name = "greet"
        mcp_tool.description = "Say hello"
        mcp_tool.inputSchema = {"properties": {"name": {"type": "string"}}}

        # Mock session with a successful call_tool response
        content_item = MagicMock()
        content_item.text = "Hello, World!"
        mock_result = MagicMock()
        mock_result.content = [content_item]

        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=mock_result)

        tool = manager._convert_mcp_tool(mcp_tool, session, "test")
        result = await tool.ainvoke({"name": "World"})
        assert "Hello, World!" in result
        session.call_tool.assert_awaited_once_with("greet", arguments={"name": "World"})

    async def test_call_tool_error(self):
        """If session.call_tool raises, the tool should return an error string."""
        manager = MCPClientManager()
        mcp_tool = MagicMock()
        mcp_tool.name = "fail"
        mcp_tool.description = "Always fails"
        mcp_tool.inputSchema = {}

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=RuntimeError("Connection lost"))

        tool = manager._convert_mcp_tool(mcp_tool, session, "test")
        result = await tool.ainvoke({})
        assert "Tool error" in result
        assert "Connection lost" in result


# =============================================================================
# close()
# =============================================================================


class TestClose:
    """Tests for MCPClientManager.close()."""

    async def test_close_clears_state(self):
        """close() should reset all internal state."""
        manager = MCPClientManager()
        manager._initialized = True
        manager._discovered_tools = [MagicMock()]

        # Add a mock connection that simulates _StdioConnection.close()
        mock_conn = AsyncMock()
        manager._connections = {"test": mock_conn}

        await manager.close()

        assert manager._initialized is False
        assert manager._discovered_tools == []
        assert manager._connections == {}
        mock_conn.close.assert_awaited_once()
