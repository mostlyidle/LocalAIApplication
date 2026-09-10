"""Tests for chat API routes — REST and conversation management.

Targets app/api/routes/chat.py for 46% → 80%+ coverage.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request as StarletteRequest

from app.models.db_models import Conversation, Message, ToolCallRecord
from app.models.enums import AgentType, MessageRole


# =============================================================================
# Helper: create a mock agent result
# =============================================================================


def _make_agent_result(
    content: str = "Hello!",
    agent_used: str = "chat",
    tool_calls: list | None = None,
) -> dict[str, Any]:
    """Build a mock result dict matching run_agent() return shape."""
    mock_msg = MagicMock()
    mock_msg.content = content
    return {
        "messages": [mock_msg],
        "metadata": {"agent_used": agent_used},
        "tool_calls": tool_calls or [],
    }


# =============================================================================
# POST /chat
# =============================================================================


class TestSendMessage:
    """Tests for the POST /chat endpoint."""

    async def test_sends_message_and_gets_response(self, client: AsyncClient):
        """Basic chat round-trip: send message, receive assistant response."""
        result = _make_agent_result("Hi there!", "chat")
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            resp = await client.post(
                "/api/v1/chat",
                json={"content": "Hello"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Hi there!"
        assert data["agent_used"] == "chat"
        assert data["conversation_id"] is not None

    async def test_reuses_existing_conversation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Providing conversation_id reuses the conversation."""
        # Create a conversation first
        conv = Conversation(id="test-conv-123", title="Test")
        db_session.add(conv)
        await db_session.commit()

        result = _make_agent_result("Response", "chat")
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            resp = await client.post(
                "/api/v1/chat",
                json={"content": "Follow up", "conversation_id": "test-conv-123"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == "test-conv-123"

    async def test_persists_tool_calls(self, client: AsyncClient):
        """Tool calls in the result are persisted and returned."""
        tool_calls = [
            {
                "tool_name": "sql_query_tool",
                "tool_input": {"sql": "SELECT 1"},
                "tool_output": "1",
            }
        ]
        result = _make_agent_result("Query result", "sql", tool_calls=tool_calls)
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            resp = await client.post(
                "/api/v1/chat",
                json={"content": "How many users?"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool_name"] == "sql_query_tool"

    async def test_updates_conversation_title(self, client: AsyncClient):
        """First message in a new conversation sets the title."""
        result = _make_agent_result("Response", "chat")
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            resp = await client.post(
                "/api/v1/chat",
                json={"content": "What is the meaning of life?"},
            )

        assert resp.status_code == 200

    async def test_validation_error_on_empty_content(self, client: AsyncClient):
        """Empty content should fail validation."""
        resp = await client.post(
            "/api/v1/chat",
            json={"content": ""},
        )
        assert resp.status_code == 422

    async def test_validation_error_on_missing_content(self, client: AsyncClient):
        """Missing content field should fail validation."""
        resp = await client.post(
            "/api/v1/chat",
            json={},
        )
        assert resp.status_code == 422

    async def test_fallback_response_when_no_messages(self, client: AsyncClient):
        """When agent returns no messages, fallback text is used."""
        result = {
            "messages": [],
            "metadata": {"agent_used": "chat"},
            "tool_calls": [],
        }
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            resp = await client.post(
                "/api/v1/chat",
                json={"content": "Hello"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "sorry" in data["content"].lower() or "unable" in data["content"].lower()


# =============================================================================
# POST /chat — direct handler tests (exercises lines 59-115 under coverage)
# =============================================================================


class TestSendMessageDirect:
    """Test the send_message handler directly to guarantee line coverage."""

    @staticmethod
    def _mock_request(path: str = "/api/v1/chat") -> StarletteRequest:
        """Build a minimal Starlette Request for direct handler testing.

        slowapi's ``@limiter.limit()`` decorator expects a real Request object
        with ``client``, ``headers``, and ``app.state.limiter`` attributes.
        """
        mock_app = MagicMock()
        mock_app.state = MagicMock()
        from app.api.middleware.rate_limiting import limiter

        mock_app.state.limiter = limiter
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
            "client": ("testclient-direct", 0),
            "app": mock_app,
        }
        return StarletteRequest(scope)

    async def test_full_handler_path_new_conversation(self, db_session: AsyncSession):
        """Exercise the full send_message handler with a real DB session."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        result = _make_agent_result("Direct response", "chat")
        body = ChatMessageRequest(content="Direct test message")

        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            response = await send_message(request=self._mock_request(), body=body, db=db_session)

        assert response.content == "Direct response"
        assert response.agent_used == "chat"
        assert response.conversation_id is not None
        assert response.tool_calls == []

    async def test_full_handler_with_tool_calls(self, db_session: AsyncSession):
        """Exercise tool call persistence through the handler."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        tool_calls = [
            {
                "tool_name": "web_search",
                "tool_input": {"query": "test"},
                "tool_output": "result from web",
            },
            {
                "tool_name": "calculator",
                "tool_input": {"expression": "2+2"},
                "tool_output": "4",
            },
        ]
        result = _make_agent_result("Combined result", "web", tool_calls=tool_calls)
        body = ChatMessageRequest(content="Search and calculate")

        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            response = await send_message(request=self._mock_request(), body=body, db=db_session)

        assert response.content == "Combined result"
        assert response.agent_used == "web"
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].tool_name == "web_search"
        assert response.tool_calls[1].tool_name == "calculator"

    async def test_title_update_on_first_message(self, db_session: AsyncSession):
        """Conversation title is set from the first user message content."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        result = _make_agent_result("Response", "chat")
        conv_id = "title-test-conv"

        # Create a fresh conversation with default title
        conv = Conversation(id=conv_id, title="New Conversation")
        db_session.add(conv)
        await db_session.flush()

        body = ChatMessageRequest(
            content="What is the meaning of life?",
            conversation_id=conv_id,
        )
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            response = await send_message(request=self._mock_request(), body=body, db=db_session)

        assert response.conversation_id == conv_id
        # Verify conversation title was updated
        from sqlalchemy import select

        stmt = select(Conversation).where(Conversation.id == conv_id)
        db_result = await db_session.execute(stmt)
        updated_conv = db_result.scalar_one()
        assert updated_conv.title == "What is the meaning of life?"

    async def test_existing_conversation_keeps_title(self, db_session: AsyncSession):
        """An existing conversation with a custom title keeps it."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        result = _make_agent_result("Response", "chat")
        conv_id = "keep-title-conv"

        conv = Conversation(id=conv_id, title="My Custom Title")
        db_session.add(conv)
        await db_session.flush()

        body = ChatMessageRequest(content="Follow up", conversation_id=conv_id)
        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            response = await send_message(request=self._mock_request(), body=body, db=db_session)

        from sqlalchemy import select

        stmt = select(Conversation).where(Conversation.id == conv_id)
        db_result = await db_session.execute(stmt)
        updated_conv = db_result.scalar_one()
        assert updated_conv.title == "My Custom Title"

    async def test_messages_persisted_to_db(self, db_session: AsyncSession):
        """Both user and assistant messages are persisted after send_message."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        result = _make_agent_result("Persisted reply", "chat")
        body = ChatMessageRequest(content="Persist me")

        with patch("app.api.routes.chat.run_agent", new_callable=AsyncMock, return_value=result):
            response = await send_message(request=self._mock_request(), body=body, db=db_session)

        from sqlalchemy import select

        stmt = select(Message).where(Message.conversation_id == response.conversation_id)
        db_result = await db_session.execute(stmt)
        msgs = db_result.scalars().all()
        assert len(msgs) == 2
        assert msgs[0].role == MessageRole.USER
        assert msgs[0].content == "Persist me"
        assert msgs[1].role == MessageRole.ASSISTANT
        assert msgs[1].content == "Persisted reply"

    async def test_run_agent_receives_existing_messages(self, db_session: AsyncSession):
        """Existing messages are loaded and passed to run_agent."""
        from app.api.routes.chat import send_message
        from app.models.schemas import ChatMessageRequest

        conv_id = "ctx-conv"
        conv = Conversation(id=conv_id, title="Context Test")
        db_session.add(conv)
        db_session.add(Message(conversation_id=conv_id, role=MessageRole.USER, content="First msg"))
        db_session.add(
            Message(conversation_id=conv_id, role=MessageRole.ASSISTANT, content="First reply")
        )
        await db_session.flush()

        result = _make_agent_result("Second reply", "chat")
        body = ChatMessageRequest(content="Second msg", conversation_id=conv_id)

        mock_run = AsyncMock(return_value=result)
        with patch("app.api.routes.chat.run_agent", mock_run):
            await send_message(request=self._mock_request(), body=body, db=db_session)

        # Verify run_agent was called with existing_messages containing 2 prior messages
        call_kwargs = mock_run.call_args
        assert len(call_kwargs.kwargs["existing_messages"]) == 2


# =============================================================================
# GET /chat/conversations
# =============================================================================


class TestListConversations:
    """Tests for GET /chat/conversations."""

    async def test_returns_empty_list(self, client: AsyncClient):
        """No conversations returns empty list."""
        resp = await client.get("/api/v1/chat/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_conversations(self, client: AsyncClient, db_session: AsyncSession):
        """Conversations are returned with metadata."""
        conv = Conversation(id="conv-1", title="Test Chat")
        db_session.add(conv)
        msg = Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
        )
        db_session.add(msg)
        await db_session.commit()

        resp = await client.get("/api/v1/chat/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["title"] == "Test Chat"
        assert data[0]["message_count"] >= 1


class TestListConversationsDirect:
    """Direct tests for list_conversations to cover lines 204-206."""

    async def test_list_conversations_with_messages(self, db_session: AsyncSession):
        """Exercise list_conversations directly to cover summary building."""
        from app.api.routes.chat import list_conversations

        conv = Conversation(id="list-conv-1", title="Listed Chat")
        db_session.add(conv)
        db_session.add(Message(conversation_id="list-conv-1", role=MessageRole.USER, content="Hi"))
        await db_session.flush()

        result = await list_conversations(db=db_session)
        assert len(result) >= 1
        assert result[0].id == "list-conv-1"
        assert result[0].title == "Listed Chat"
        assert result[0].message_count == 1

    async def test_list_conversations_without_messages(self, db_session: AsyncSession):
        """A conversation with no messages uses created_at as last_message_at."""
        from app.api.routes.chat import list_conversations

        conv = Conversation(id="empty-conv", title="Empty")
        db_session.add(conv)
        await db_session.flush()

        result = await list_conversations(db=db_session)
        assert len(result) == 1
        assert result[0].message_count == 0
        assert result[0].last_message_at == conv.created_at

    async def test_list_conversations_ordering(self, db_session: AsyncSession):
        """Conversations are ordered by updated_at descending."""
        from app.api.routes.chat import list_conversations

        c1 = Conversation(id="ord-1", title="First")
        c2 = Conversation(id="ord-2", title="Second")
        db_session.add(c1)
        await db_session.flush()
        db_session.add(c2)
        await db_session.flush()

        result = await list_conversations(db=db_session)
        assert len(result) == 2
        # Most recently created/updated should be first
        assert result[0].id == "ord-2"


# =============================================================================
# GET /chat/conversations/{conversation_id}
# =============================================================================


class TestGetConversation:
    """Tests for GET /chat/conversations/{conversation_id}."""

    async def test_returns_conversation_with_messages(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Returns conversation detail with messages."""
        conv = Conversation(id="detail-conv", title="Detail Test")
        db_session.add(conv)
        msg = Message(
            conversation_id="detail-conv",
            role=MessageRole.USER,
            content="Hi",
        )
        db_session.add(msg)
        await db_session.commit()

        resp = await client.get("/api/v1/chat/conversations/detail-conv")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "detail-conv"
        assert data["title"] == "Detail Test"
        assert len(data["messages"]) >= 1

    async def test_returns_404_for_unknown_conversation(self, client: AsyncClient):
        """Unknown conversation_id returns 404."""
        resp = await client.get("/api/v1/chat/conversations/nonexistent")
        assert resp.status_code == 404


class TestGetConversationDirect:
    """Direct tests for get_conversation to cover lines 237-242."""

    async def test_get_conversation_with_tool_calls(self, db_session: AsyncSession):
        """Exercise message serialization including tool_calls (lines 237-242)."""
        from app.api.routes.chat import get_conversation

        conv = Conversation(id="detail-tc", title="With Tools")
        db_session.add(conv)
        msg = Message(
            conversation_id="detail-tc",
            role=MessageRole.ASSISTANT,
            content="Query result",
            agent_type="sql",
        )
        db_session.add(msg)
        await db_session.flush()

        tc = ToolCallRecord(
            message_id=msg.id,
            tool_name="sql_query_tool",
            tool_input=json.dumps({"sql": "SELECT 1"}),
            tool_output="[[1]]",
            duration_ms=42.5,
        )
        db_session.add(tc)
        await db_session.flush()

        result = await get_conversation(conversation_id="detail-tc", db=db_session)
        assert result["id"] == "detail-tc"
        assert len(result["messages"]) == 1
        msg_data = result["messages"][0]
        assert msg_data["content"] == "Query result"
        assert msg_data["agent_type"] == "sql"
        assert len(msg_data["tool_calls"]) == 1
        assert msg_data["tool_calls"][0]["tool_name"] == "sql_query_tool"
        assert msg_data["tool_calls"][0]["tool_input"] == {"sql": "SELECT 1"}
        assert msg_data["tool_calls"][0]["tool_output"] == "[[1]]"
        assert msg_data["tool_calls"][0]["duration_ms"] == 42.5

    async def test_get_conversation_with_null_tool_input(self, db_session: AsyncSession):
        """Tool call with null tool_input returns empty dict."""
        from app.api.routes.chat import get_conversation

        conv = Conversation(id="null-ti", title="Null Input")
        db_session.add(conv)
        msg = Message(conversation_id="null-ti", role=MessageRole.ASSISTANT, content="result")
        db_session.add(msg)
        await db_session.flush()

        tc = ToolCallRecord(
            message_id=msg.id,
            tool_name="some_tool",
            tool_input="",
            tool_output=None,
        )
        db_session.add(tc)
        await db_session.flush()

        result = await get_conversation(conversation_id="null-ti", db=db_session)
        tc_data = result["messages"][0]["tool_calls"][0]
        assert tc_data["tool_output"] is None

    async def test_get_conversation_not_found_raises(self, db_session: AsyncSession):
        """Calling get_conversation with unknown id raises NotFoundError."""
        from app.api.middleware.error_handler import NotFoundError
        from app.api.routes.chat import get_conversation

        with pytest.raises(NotFoundError):
            await get_conversation(conversation_id="nope", db=db_session)

    async def test_get_conversation_timestamps(self, db_session: AsyncSession):
        """Verify created_at and updated_at are ISO-formatted strings."""
        from app.api.routes.chat import get_conversation

        conv = Conversation(id="ts-conv", title="Timestamps")
        db_session.add(conv)
        await db_session.flush()

        result = await get_conversation(conversation_id="ts-conv", db=db_session)
        assert "T" in result["created_at"]  # ISO format
        assert "T" in result["updated_at"]


# =============================================================================
# DELETE /chat/conversations/{conversation_id}
# =============================================================================


class TestDeleteConversation:
    """Tests for DELETE /chat/conversations/{conversation_id}."""

    async def test_deletes_conversation(self, client: AsyncClient, db_session: AsyncSession):
        """Deleting an existing conversation returns success."""
        conv = Conversation(id="del-conv", title="To Delete")
        db_session.add(conv)
        await db_session.commit()

        resp = await client.delete("/api/v1/chat/conversations/del-conv")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"

    async def test_delete_nonexistent_returns_404(self, client: AsyncClient):
        """Deleting a nonexistent conversation returns 404."""
        resp = await client.delete("/api/v1/chat/conversations/nope")
        assert resp.status_code == 404


class TestDeleteConversationDirect:
    """Direct tests for delete_conversation to cover lines 285-293."""

    async def test_delete_conversation_success(self, db_session: AsyncSession):
        """Exercise delete_conversation directly."""
        from app.api.routes.chat import delete_conversation

        conv = Conversation(id="direct-del", title="Delete Me")
        db_session.add(conv)
        await db_session.flush()

        result = await delete_conversation(conversation_id="direct-del", db=db_session)
        assert result["status"] == "deleted"
        assert result["conversation_id"] == "direct-del"

        # Verify it's gone
        from sqlalchemy import select

        stmt = select(Conversation).where(Conversation.id == "direct-del")
        db_result = await db_session.execute(stmt)
        assert db_result.scalar_one_or_none() is None

    async def test_delete_conversation_with_messages(self, db_session: AsyncSession):
        """Cascade deletes messages when conversation is deleted."""
        from app.api.routes.chat import delete_conversation

        conv = Conversation(id="cascade-del", title="Cascade")
        db_session.add(conv)
        db_session.add(Message(conversation_id="cascade-del", role=MessageRole.USER, content="bye"))
        await db_session.flush()

        result = await delete_conversation(conversation_id="cascade-del", db=db_session)
        assert result["status"] == "deleted"

    async def test_delete_conversation_not_found_raises(self, db_session: AsyncSession):
        """Deleting nonexistent conversation raises NotFoundError."""
        from app.api.middleware.error_handler import NotFoundError
        from app.api.routes.chat import delete_conversation

        with pytest.raises(NotFoundError):
            await delete_conversation(conversation_id="ghost", db=db_session)


# =============================================================================
# Helper: _get_or_create_conversation (lines 305-312)
# =============================================================================


class TestGetOrCreateConversation:
    """Tests for _get_or_create_conversation helper."""

    async def test_creates_new_conversation(self, db_session: AsyncSession):
        """Creates a new conversation when none exists."""
        from app.api.routes.chat import _get_or_create_conversation

        conv = await _get_or_create_conversation(db_session, "new-conv-id")
        assert conv.id == "new-conv-id"
        assert conv.title == "New Conversation"

    async def test_returns_existing_conversation(self, db_session: AsyncSession):
        """Returns existing conversation without creating duplicate."""
        from app.api.routes.chat import _get_or_create_conversation

        existing = Conversation(id="existing-conv", title="Already Here")
        db_session.add(existing)
        await db_session.flush()

        conv = await _get_or_create_conversation(db_session, "existing-conv")
        assert conv.id == "existing-conv"
        assert conv.title == "Already Here"

    async def test_new_conversation_is_persisted(self, db_session: AsyncSession):
        """A newly created conversation is visible in the database after flush."""
        from sqlalchemy import select

        from app.api.routes.chat import _get_or_create_conversation

        await _get_or_create_conversation(db_session, "persisted-conv")

        stmt = select(Conversation).where(Conversation.id == "persisted-conv")
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is not None


# =============================================================================
# Helper functions
# =============================================================================


class TestExtractResponseContent:
    """Tests for the _extract_response_content helper."""

    def test_extracts_from_last_message(self):
        """Extracts content from the last message in the result."""
        from app.api.routes.chat import _extract_response_content

        msg = MagicMock()
        msg.content = "The answer is 42"
        result = _extract_response_content({"messages": [msg]})
        assert result == "The answer is 42"

    def test_fallback_when_no_messages(self):
        """Returns fallback text when no messages in result."""
        from app.api.routes.chat import _extract_response_content

        result = _extract_response_content({"messages": []})
        assert "sorry" in result.lower()

    def test_fallback_when_messages_key_missing(self):
        """Returns fallback when 'messages' key is not present."""
        from app.api.routes.chat import _extract_response_content

        result = _extract_response_content({})
        assert "sorry" in result.lower()


class TestLoadLangchainMessages:
    """Tests for _load_langchain_messages helper."""

    async def test_returns_empty_for_no_messages(self, db_session: AsyncSession):
        """No prior messages returns empty list."""
        from app.api.routes.chat import _load_langchain_messages

        result = await _load_langchain_messages(db_session, "nonexistent-conv")
        assert result == []

    async def test_converts_messages_to_langchain_types(self, db_session: AsyncSession):
        """Stored messages are converted to HumanMessage/AIMessage."""
        from langchain_core.messages import AIMessage, HumanMessage

        from app.api.routes.chat import _load_langchain_messages

        conv = Conversation(id="lc-conv", title="Test")
        db_session.add(conv)
        db_session.add(Message(conversation_id="lc-conv", role=MessageRole.USER, content="Hello"))
        db_session.add(
            Message(
                conversation_id="lc-conv",
                role=MessageRole.ASSISTANT,
                content="Hi back",
            )
        )
        await db_session.commit()

        result = await _load_langchain_messages(db_session, "lc-conv")
        assert len(result) == 2
        assert isinstance(result[0], HumanMessage)
        assert isinstance(result[1], AIMessage)
        assert result[0].content == "Hello"
        assert result[1].content == "Hi back"

    async def test_converts_system_message(self, db_session: AsyncSession):
        """System messages are converted to SystemMessage (lines 336-337)."""
        from langchain_core.messages import SystemMessage

        from app.api.routes.chat import _load_langchain_messages

        conv = Conversation(id="sys-conv", title="System")
        db_session.add(conv)
        db_session.add(
            Message(
                conversation_id="sys-conv",
                role=MessageRole.SYSTEM,
                content="You are a helpful assistant.",
            )
        )
        await db_session.commit()

        result = await _load_langchain_messages(db_session, "sys-conv")
        assert len(result) == 1
        assert isinstance(result[0], SystemMessage)
        assert result[0].content == "You are a helpful assistant."

    async def test_skips_tool_messages(self, db_session: AsyncSession):
        """Tool messages are skipped (not converted)."""
        from app.api.routes.chat import _load_langchain_messages

        conv = Conversation(id="tool-conv", title="Tool Msg")
        db_session.add(conv)
        db_session.add(Message(conversation_id="tool-conv", role=MessageRole.USER, content="Hi"))
        db_session.add(
            Message(conversation_id="tool-conv", role=MessageRole.TOOL, content="tool output")
        )
        db_session.add(
            Message(conversation_id="tool-conv", role=MessageRole.ASSISTANT, content="Done")
        )
        await db_session.commit()

        result = await _load_langchain_messages(db_session, "tool-conv")
        # Tool message should be skipped
        assert len(result) == 2


# =============================================================================
# WebSocket /chat/stream (lines 143-185)
# =============================================================================


class TestWebSocketStream:
    """Tests for the WebSocket /chat/stream endpoint."""

    @pytest.fixture(autouse=True)
    def mock_history(self):
        """Keep transport-only tests independent of the application database."""
        with patch("app.api.routes.chat._load_ws_history", AsyncMock(return_value=[])):
            yield

    def _make_test_client(self):
        """Build a Starlette TestClient with stream_agent mocked."""
        from starlette.testclient import TestClient

        from app.main import create_app

        app = create_app()
        return TestClient(app), app

    def _patches(self):
        """Return a combined patch context for stream_agent + persistence.

        All WebSocket integration tests mock out _persist_ws_messages so
        they don't need a live app database.
        """
        return patch(
            "app.api.routes.chat._persist_ws_messages",
            new_callable=AsyncMock,
        )

    def test_valid_message_stream(self):
        """Send a message and receive streamed token events + done."""

        async def mock_stream(**kwargs):
            yield {"type": "token", "content": "Hello"}
            yield {"type": "token", "content": " world"}
            yield {"type": "done", "metadata": {"agent_used": "chat"}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "hi"})
                r1 = ws.receive_json()
                assert r1["type"] == "token"
                assert r1["content"] == "Hello"
                r2 = ws.receive_json()
                assert r2["type"] == "token"
                assert r2["content"] == " world"
                r3 = ws.receive_json()
                assert r3["type"] == "done"

    def test_invalid_json_sends_error(self):
        """Sending invalid JSON returns an error event."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_text("not valid json {{{")
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "Invalid JSON" in resp["content"]

    def test_unknown_message_type_sends_error(self):
        """Sending an unknown message type returns an error."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "unknown_type", "content": "hello"})
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "Unknown message type" in resp["content"]

    def test_empty_content_sends_error(self):
        """Sending a message with empty content returns an error."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": ""})
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "required" in resp["content"].lower()

    def test_whitespace_only_content_sends_error(self):
        """Whitespace-only content is treated as empty."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "   "})
                resp = ws.receive_json()
                assert resp["type"] == "error"
                assert "required" in resp["content"].lower()

    def test_stream_agent_error_sends_error_and_done(self):
        """When stream_agent raises, an error event and done event are sent."""

        async def mock_stream_error(**kwargs):
            raise RuntimeError("LLM connection failed")
            yield  # noqa: unreachable — makes this an async generator

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream_error),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "hello"})
                r1 = ws.receive_json()
                assert r1["type"] == "error"
                assert "Agent error" in r1["content"]
                r2 = ws.receive_json()
                assert r2["type"] == "done"

    def test_message_with_conversation_id(self):
        """Client can provide a conversation_id."""

        async def mock_stream(**kwargs):
            yield {"type": "token", "content": "ok"}
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream) as mock,
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json(
                    {
                        "type": "message",
                        "content": "hello",
                        "conversation_id": "ws-conv-123",
                    }
                )
                ws.receive_json()  # token
                ws.receive_json()  # done

            # Verify stream_agent received the conversation_id
            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["conversation_id"] == "ws-conv-123"

    def test_message_without_conversation_id_generates_one(self):
        """When no conversation_id is provided, one is generated (uuid)."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream) as mock,
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "hello"})
                ws.receive_json()  # done

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["conversation_id"] is not None
            assert len(call_kwargs["conversation_id"]) == 36  # UUID length

    def test_multiple_messages_in_sequence(self):
        """Multiple messages can be sent over the same WebSocket connection."""
        call_count = 0

        async def mock_stream(**kwargs):
            nonlocal call_count
            call_count += 1
            yield {"type": "token", "content": f"reply {call_count}"}
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                # First message
                ws.send_json({"type": "message", "content": "first"})
                r1 = ws.receive_json()
                assert r1["content"] == "reply 1"
                ws.receive_json()  # done

                # Second message
                ws.send_json({"type": "message", "content": "second"})
                r2 = ws.receive_json()
                assert r2["content"] == "reply 2"
                ws.receive_json()  # done

    def test_tool_call_events_forwarded(self):
        """Tool call and tool result events from stream_agent are forwarded."""

        async def mock_stream(**kwargs):
            yield {"type": "tool_call", "tool": "sql_query", "input": {"sql": "SELECT 1"}}
            yield {"type": "tool_result", "tool": "sql_query", "output": "1"}
            yield {"type": "token", "content": "The result is 1"}
            yield {"type": "done", "metadata": {}}

        client, _ = self._make_test_client()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            self._patches(),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "run query"})
                r1 = ws.receive_json()
                assert r1["type"] == "tool_call"
                assert r1["tool"] == "sql_query"
                r2 = ws.receive_json()
                assert r2["type"] == "tool_result"
                r3 = ws.receive_json()
                assert r3["type"] == "token"
                r4 = ws.receive_json()
                assert r4["type"] == "done"

    def test_persistence_called_after_stream(self):
        """_persist_ws_messages is called with correct args after streaming."""

        async def mock_stream(**kwargs):
            yield {"type": "agent_switch", "agent": "sql"}
            yield {"type": "tool_call", "tool": "sql_query", "input": {"sql": "SELECT 1"}}
            yield {"type": "tool_result", "tool": "sql_query", "output": "[[1]]"}
            yield {"type": "token", "content": "Result: 1"}
            yield {"type": "done", "metadata": {"agent_used": "sql"}}

        client, _ = self._make_test_client()
        mock_persist = AsyncMock()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream),
            patch("app.api.routes.chat._persist_ws_messages", mock_persist),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json(
                    {
                        "type": "message",
                        "content": "run sql",
                        "conversation_id": "persist-test",
                    }
                )
                # Drain all events
                for _ in range(5):
                    ws.receive_json()

        # Verify persistence was called
        mock_persist.assert_called_once()
        call_kwargs = mock_persist.call_args.kwargs
        assert call_kwargs["conversation_id"] == "persist-test"
        assert call_kwargs["user_content"] == "run sql"
        assert call_kwargs["assistant_content"] == "Result: 1"
        assert call_kwargs["agent_used"] == "sql"
        assert len(call_kwargs["tool_calls_data"]) == 1
        assert call_kwargs["tool_calls_data"][0]["tool_name"] == "sql_query"
        assert call_kwargs["tool_calls_data"][0]["tool_output"] == "[[1]]"

    def test_persistence_called_even_on_agent_error(self):
        """Persistence is attempted even when stream_agent raises."""

        async def mock_stream_error(**kwargs):
            raise RuntimeError("boom")
            yield  # noqa: unreachable

        client, _ = self._make_test_client()
        mock_persist = AsyncMock()
        with (
            patch("app.api.routes.chat.stream_agent", side_effect=mock_stream_error),
            patch("app.api.routes.chat._persist_ws_messages", mock_persist),
        ):
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "hello"})
                ws.receive_json()  # error
                ws.receive_json()  # done

        # Persistence still called (empty content, no tool calls)
        mock_persist.assert_called_once()
        call_kwargs = mock_persist.call_args.kwargs
        assert call_kwargs["assistant_content"] == ""


# =============================================================================
# _persist_ws_messages helper (lines 300-370)
# =============================================================================


def _mock_session_factory(real_session: AsyncSession):
    """Create a mock session factory that yields the test db_session.

    This allows _persist_ws_messages to use the test database session
    instead of creating its own from the real app engine.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_ctx():
        yield real_session

    mock_factory = MagicMock()
    mock_factory.return_value = _session_ctx()
    # Make the factory callable — each call returns a new context
    mock_factory.side_effect = lambda: _session_ctx()
    return mock_factory


class TestPersistWsMessages:
    """Tests for the _persist_ws_messages helper function."""

    async def test_persists_user_and_assistant_messages(self, db_session: AsyncSession):
        """User and assistant messages are persisted to the database."""
        from app.api.routes.chat import _persist_ws_messages

        conv_id = "ws-persist-test"
        with patch(
            "app.services.database.get_app_session_factory",
            return_value=_mock_session_factory(db_session),
        ):
            await _persist_ws_messages(
                conversation_id=conv_id,
                user_content="Hello from WS",
                assistant_content="Hi back from WS",
                agent_used="chat",
                tool_calls_data=[],
            )

        from sqlalchemy import select

        stmt = select(Message).where(Message.conversation_id == conv_id)
        result = await db_session.execute(stmt)
        msgs = result.scalars().all()
        assert len(msgs) == 2
        assert msgs[0].role == MessageRole.USER
        assert msgs[0].content == "Hello from WS"
        assert msgs[1].role == MessageRole.ASSISTANT
        assert msgs[1].content == "Hi back from WS"
        assert msgs[1].agent_type == "chat"

    async def test_persists_tool_calls(self, db_session: AsyncSession):
        """Tool call records are persisted alongside the assistant message."""
        from app.api.routes.chat import _persist_ws_messages

        conv_id = "ws-tools-test"
        tool_calls = [
            {
                "tool_name": "sql_query_tool",
                "tool_input": {"sql": "SELECT 1"},
                "tool_output": "[[1]]",
            }
        ]
        with patch(
            "app.services.database.get_app_session_factory",
            return_value=_mock_session_factory(db_session),
        ):
            await _persist_ws_messages(
                conversation_id=conv_id,
                user_content="query",
                assistant_content="result",
                agent_used="sql",
                tool_calls_data=tool_calls,
            )

        from sqlalchemy import select

        stmt = select(Message).where(
            Message.conversation_id == conv_id,
            Message.role == MessageRole.ASSISTANT,
        )
        result = await db_session.execute(stmt)
        assistant_msg = result.scalar_one()

        stmt = select(ToolCallRecord).where(ToolCallRecord.message_id == assistant_msg.id)
        result = await db_session.execute(stmt)
        tcs = result.scalars().all()
        assert len(tcs) == 1
        assert tcs[0].tool_name == "sql_query_tool"
        assert json.loads(tcs[0].tool_input) == {"sql": "SELECT 1"}
        assert tcs[0].tool_output == "[[1]]"

    async def test_sets_conversation_title_from_first_message(self, db_session: AsyncSession):
        """Conversation title is set from the first user message."""
        from app.api.routes.chat import _persist_ws_messages

        conv_id = "ws-title-test"
        with patch(
            "app.services.database.get_app_session_factory",
            return_value=_mock_session_factory(db_session),
        ):
            await _persist_ws_messages(
                conversation_id=conv_id,
                user_content="What is the weather today?",
                assistant_content="I can't check weather.",
                agent_used="chat",
                tool_calls_data=[],
            )

        from sqlalchemy import select

        stmt = select(Conversation).where(Conversation.id == conv_id)
        result = await db_session.execute(stmt)
        conv = result.scalar_one()
        assert conv.title == "What is the weather today?"

    async def test_empty_assistant_content_uses_fallback(self, db_session: AsyncSession):
        """Empty assistant content is replaced with a fallback message."""
        from app.api.routes.chat import _persist_ws_messages

        conv_id = "ws-empty-test"
        with patch(
            "app.services.database.get_app_session_factory",
            return_value=_mock_session_factory(db_session),
        ):
            await _persist_ws_messages(
                conversation_id=conv_id,
                user_content="hello",
                assistant_content="",
                agent_used=None,
                tool_calls_data=[],
            )

        from sqlalchemy import select

        stmt = select(Message).where(
            Message.conversation_id == conv_id,
            Message.role == MessageRole.ASSISTANT,
        )
        result = await db_session.execute(stmt)
        assistant_msg = result.scalar_one()
        assert assistant_msg.content == "No response generated."

    async def test_db_error_is_caught_and_logged(self, db_session: AsyncSession):
        """Database errors are caught and logged, not propagated."""
        from app.api.routes.chat import _persist_ws_messages

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_factory.return_value.__aexit__ = AsyncMock()

        with patch(
            "app.services.database.get_app_session_factory",
            return_value=mock_factory,
        ):
            # Should NOT raise
            await _persist_ws_messages(
                conversation_id="fail-test",
                user_content="hello",
                assistant_content="hi",
                agent_used="chat",
                tool_calls_data=[],
            )
