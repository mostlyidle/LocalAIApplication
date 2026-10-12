"""Regression checks for persisted streaming conversation context."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.agents.orchestrator import run_agent, stream_agent
from app.dependencies import get_websocket_session
from app.main import create_app
from app.models.db_models import LEGACY_ACCOUNT_ID, Account, AccountSession, Base
from app.services.auth import AuthenticatedSession

if TYPE_CHECKING:
    from pathlib import Path


def test_stream_saves_before_done_and_loads_history(tmp_path: Path) -> None:
    """A second turn sees the first turn, including after a socket reconnect."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create_tables() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    calls = []

    async def respond(**kwargs):
        calls.append(kwargs)
        yield {"type": "token", "content": "Hello Ada"}
        yield {"type": "done", "metadata": {"agent_used": "chat"}}

    try:
        with (
            patch("app.services.database.get_app_session_factory", return_value=factory),
            patch("app.api.routes.chat.stream_agent", respond),
        ):
            app = create_app()
            app.dependency_overrides[get_websocket_session] = lambda: AuthenticatedSession(
                account=Account(
                    id=LEGACY_ACCOUNT_ID,
                    username="test-account",
                    display_name="Test Account",
                    password_hash="!test!",
                ),
                session=AccountSession(
                    id="test-session",
                    account_id=LEGACY_ACCOUNT_ID,
                    token_hash="0" * 64,
                    csrf_token="test-csrf-token",
                    expires_at=datetime.now(UTC),
                ),
            )
            client = TestClient(app)
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json({"type": "message", "content": "My name is Ada"})
                assert ws.receive_json()["type"] == "token"
                done = ws.receive_json()
                assert done["type"] == "done"
                conversation_id = done["metadata"]["conversation_id"]
            with client.websocket_connect("/api/v1/chat/stream") as ws:
                ws.send_json(
                    {
                        "type": "message",
                        "content": "What is my name?",
                        "conversation_id": conversation_id,
                    }
                )
                assert ws.receive_json()["type"] == "token"
                assert ws.receive_json()["metadata"]["conversation_id"] == conversation_id
        assert calls[0]["existing_messages"] == []
        assert [message.content for message in calls[1]["existing_messages"]] == [
            "My name is Ada",
            "Hello Ada",
        ]
    finally:
        asyncio.run(engine.dispose())


async def test_orchestrator_appends_current_message_to_history() -> None:
    history = [HumanMessage(content="My name is Ada"), AIMessage(content="Hello")]
    with patch(
        "app.agents.orchestrator.orchestrator_graph.ainvoke", AsyncMock(return_value={})
    ) as invoke:
        await run_agent("What is my name?", "conversation", existing_messages=history)
    assert [message.content for message in invoke.call_args.args[0]["messages"]] == [
        "My name is Ada",
        "Hello",
        "What is my name?",
    ]
    assert len(history) == 2


async def test_orchestrator_loads_memory_separately_from_user_history() -> None:
    with (
        patch(
            "app.services.memory_context.load_account_memory_context",
            AsyncMock(return_value='[{"type":"preference","content":"Concise"}]'),
        ),
        patch(
            "app.agents.orchestrator.orchestrator_graph.ainvoke", AsyncMock(return_value={})
        ) as invoke,
    ):
        await run_agent("Hello", "conversation", owner_id=LEGACY_ACCOUNT_ID)

    state = invoke.call_args.args[0]
    assert state["memory_context"] == '[{"type":"preference","content":"Concise"}]'
    assert [message.content for message in state["messages"]] == ["Hello"]


async def test_stream_excludes_classifier_tokens_and_keeps_current_turn() -> None:
    from langchain_core.messages import AIMessageChunk

    states = []

    async def events(state, **kwargs):
        states.append(state)
        for node, content in [("classify_intent", '{"agent":"chat"}'), ("chat", "Ada")]:
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": node},
                "data": {"chunk": AIMessageChunk(content=content)},
            }

    with patch("app.agents.orchestrator.orchestrator_graph.astream_events", events):
        output = [
            event
            async for event in stream_agent(
                "What is my name?",
                "conversation",
                existing_messages=[HumanMessage(content="Ada")],
            )
        ]
    assert output == [{"type": "token", "content": "Ada"}]
    assert states[0]["messages"][-1].content == "What is my name?"
