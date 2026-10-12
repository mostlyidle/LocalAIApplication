from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from starlette.testclient import TestClient

from app.agents.registry import AgentRegistry
from app.main import create_app
from app.models.profile_schemas import TaskRequest
from app.prompt_store import PromptStore
from tests.test_services.test_task_runner_images import _runner


@pytest.mark.parametrize("profile", ["chat", "sql", "web"])
def test_selected_graph_profile_streams_tokens_and_persists_final_state(
    profile: str, authenticated_test_session
) -> None:
    app = create_app()
    from app.dependencies import get_websocket_session, websocket_session_is_active

    app.dependency_overrides[get_websocket_session] = lambda: authenticated_test_session
    app.dependency_overrides[websocket_session_is_active] = lambda: True
    directory = Path(__file__).resolve().parents[2] / "app" / "prompts"
    app.state.agent_registry = AgentRegistry(directory, PromptStore(directory))
    persist = AsyncMock(return_value=True)

    async def stream(**kwargs):
        assert kwargs["forced_agent"] == profile
        yield {"type": "token", "content": "Hello"}
        assert persist.await_count == 0
        yield {"type": "token", "content": " world"}
        yield {"type": "done", "metadata": {"agent_used": profile}, "state": {"messages": [AIMessage(content="Hello world")], "metadata": {"agent_used": profile}, "tool_calls": []}}

    with (
        patch("app.api.routes.chat.stream_agent", side_effect=stream),
        patch("app.api.routes.chat._load_ws_history", AsyncMock(return_value=[])),
        patch("app.api.routes.chat._persist_ws_messages", persist),
    ):
        with TestClient(app).websocket_connect(
            "/api/v1/chat/stream", headers={"origin": "http://localhost:3000"}
        ) as ws:
            ws.send_json({"type": "message", "content": "Hi", "agent_name": profile})
            assert ws.receive_json() == {"type": "token", "content": "Hello"}
            assert ws.receive_json() == {"type": "token", "content": " world"}
            done = ws.receive_json()
            assert done["type"] == "done" and done["metadata"]["execution"]["answer"] == "Hello world"
    persist.assert_awaited_once()
    assert persist.call_args.kwargs["assistant_content"] == "Hello world"
    assert persist.call_args.kwargs["execution_metadata"]["agent"] == profile


async def test_specialist_streams_incrementally_and_clears_callback_between_requests() -> None:
    async def stream(messages):
        yield AIMessageChunk(content="First")
        yield AIMessageChunk(content=" second")
    model = SimpleNamespace(astream=stream, ainvoke=AsyncMock(return_value=AIMessage(content="Non-streamed")))
    callback = AsyncMock()
    runner = _runner()
    request = TaskRequest(prompt="Summarize", agent_name="document_analytics", context="Evidence")
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        streamed = await runner.run(request, request_id="first", on_token=callback)
        ordinary = await runner.run(request, request_id="second")
    assert [call.args[0] for call in callback.await_args_list] == ["First", " second"]
    assert streamed.answer == "First second" and ordinary.answer == "Non-streamed"
    model.ainvoke.assert_awaited_once()


async def test_auto_rag_execution_survives_rest_history_reload(client) -> None:
    execution = {"agent": "rag", "answer": "Friday [guide:0]", "artifacts": {"citations": [{"asset_id": "guide", "chunk_index": 0, "page": 2}]}}
    state = {"messages": [AIMessage(content=execution["answer"])], "metadata": {"agent_used": "rag", "execution": execution}, "tool_calls": [], "memory_context": '[{"type":"past_conversation","conversation_id":"source-chat","title":"Kitchen plans","content":"summary"}]'}
    expected_execution = {
        **execution,
        "artifacts": {
            **execution["artifacts"],
            "memory_sources": [{"conversation_id": "source-chat", "title": "Kitchen plans"}],
        },
    }
    with patch("app.api.routes.chat.run_agent", AsyncMock(return_value=state)):
        response = await client.post("/api/v1/chat", json={"content": "Search documents for deadline"})
    assert response.status_code == 200 and response.json()["execution"] == expected_execution
    history = await client.get(f"/api/v1/chat/conversations/{response.json()['conversation_id']}")
    assert history.json()["messages"][-1]["execution"] == expected_execution


def test_auto_rag_stream_persists_terminal_citation_metadata(
    authenticated_test_session,
) -> None:
    execution = {"agent": "rag", "artifacts": {"citations": [{"asset_id": "guide", "chunk_index": 0}]}}
    async def stream(**kwargs):
        yield {"type": "token", "content": "Friday"}
        yield {
            "type": "done",
            "metadata": {"agent_used": "rag", "execution": execution},
            "state": {
                "memory_context": '[{"type":"past_conversation","conversation_id":"source-chat","title":"Kitchen plans","content":"summary"}]'
            },
        }
    expected_execution = {
        **execution,
        "artifacts": {
            **execution["artifacts"],
            "memory_sources": [{"conversation_id": "source-chat", "title": "Kitchen plans"}],
        },
    }
    persist = AsyncMock(return_value=True)
    with (
        patch("app.api.routes.chat.stream_agent", side_effect=stream),
        patch("app.api.routes.chat._load_ws_history", AsyncMock(return_value=[])),
        patch("app.api.routes.chat._persist_ws_messages", persist),
    ):
        app = create_app()
        from app.dependencies import get_websocket_session, websocket_session_is_active

        app.dependency_overrides[get_websocket_session] = lambda: authenticated_test_session
        app.dependency_overrides[websocket_session_is_active] = lambda: True
        with TestClient(app).websocket_connect(
            "/api/v1/chat/stream", headers={"origin": "http://localhost:3000"}
        ) as ws:
            ws.send_json({"type": "message", "content": "Search documents"})
            assert ws.receive_json()["type"] == "token"
            assert ws.receive_json()["metadata"]["execution"] == expected_execution
    assert persist.call_args.kwargs["execution_metadata"] == expected_execution


async def test_concurrent_specialist_streams_keep_callbacks_isolated() -> None:
    async def stream(messages):
        name = "alpha" if "alpha" in messages[1].content else "beta"
        yield AIMessageChunk(content=name)
        await asyncio.sleep(0)
        yield AIMessageChunk(content=name)
    model = SimpleNamespace(astream=stream)
    callbacks = [AsyncMock(), AsyncMock()]
    runner = _runner()
    with patch("app.services.task_runner.llm_service.get_chat_model", return_value=model):
        results = await asyncio.gather(*[
            runner.run(TaskRequest(prompt=name, agent_name="document_analytics", context="Evidence"), request_id=name, on_token=callback)
            for name, callback in zip(["alpha", "beta"], callbacks, strict=True)
        ])
    assert [result.answer for result in results] == ["alphaalpha", "betabeta"]
    assert [call.args[0] for call in callbacks[0].await_args_list] == ["alpha", "alpha"]
    assert [call.args[0] for call in callbacks[1].await_args_list] == ["beta", "beta"]


async def test_deterministic_graph_completion_emits_answer_without_leaking_private_state() -> None:
    from app.agents.orchestrator import stream_agent
    async def events(*args, **kwargs):
        yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"messages": [AIMessage(content="No evidence")], "metadata": {"agent_used": "rag"}}}}
    with patch("app.agents.orchestrator.orchestrator_graph.astream_events", side_effect=events):
        output = [event async for event in stream_agent("Search", "conversation")]
    assert output[0] == {"type": "token", "content": "No evidence"}
    assert output[1]["type"] == "done"
