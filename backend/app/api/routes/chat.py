"""Chat endpoints — REST and WebSocket streaming.

Provides:
    POST /chat          — Send a message, get a complete response.
    WS   /chat/stream   — WebSocket for real-time streaming responses.
    GET  /chat/conversations       — List all conversations.
    GET  /chat/conversations/{id}  — Get a conversation with messages.
    DELETE /chat/conversations/{id} — Delete a conversation.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable  # noqa: TC003
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002
from sqlalchemy.orm import selectinload

from app.agents.orchestrator import run_agent, stream_agent
from app.api.middleware.error_handler import AppError
from app.api.middleware.rate_limiting import limiter
from app.config import settings
from app.dependencies import (
    WEBSOCKET_SESSION_RECHECK_SECONDS,
    get_authenticated_session,
    get_db,
    get_websocket_session,
    websocket_session_is_active,
)
from app.models.db_models import Conversation, Document, Message, ToolCallRecord
from app.models.enums import MessageRole
from app.models.profile_schemas import AgentResult, ExecutionMetadata, TaskRequest
from app.models.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ConversationSummary,
    ToolCallInfo,
)
from app.services.auth import AuthenticatedSession  # noqa: TC001

logger = structlog.get_logger(__name__)
router = APIRouter()
MAX_CONTEXT_MESSAGES = 40
MAX_CONTEXT_CHARACTERS = 40_000


# ---------------------------------------------------------------------------
# POST /chat — synchronous (non-streaming) chat
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatMessageResponse)
@limiter.limit(settings.rate_limit_llm)
async def send_message(
    request: Request,
    body: ChatMessageRequest,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ChatMessageResponse:
    """Send a chat message and receive a complete response.

    Creates or reuses a conversation, invokes the orchestrator to classify
    intent and route to the appropriate agent, then persists both the user
    message and assistant response.
    """
    conversation_id = body.conversation_id or str(uuid.uuid4())
    owner_id = authenticated.account.id
    conversation = await _get_or_create_conversation(db, conversation_id, owner_id)

    if body.agent_name:
        execution = await _execute_selected_profile(
            request.app,
            body.model_copy(update={"conversation_id": conversation_id}),
            owner_id=owner_id,
            db=db,
        )
        db.add(
            Message(conversation_id=conversation_id, role=MessageRole.USER, content=body.content)
        )
        assistant_msg = Message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=execution.answer,
            agent_type=execution.agent,
            execution_metadata=json.dumps(execution.model_dump(mode="json")),
        )
        db.add(assistant_msg)
        tool_calls_data = execution.artifacts.get("tool_calls", [])
        await db.flush()
        for tc in tool_calls_data:
            db.add(
                ToolCallRecord(
                    message_id=assistant_msg.id,
                    tool_name=tc.get("tool_name", ""),
                    tool_input=json.dumps(tc.get("tool_input", {})),
                    tool_output=tc.get("tool_output"),
                )
            )
        if conversation.title == "New Conversation":
            conversation.title = body.content[:80].strip()
        await db.commit()
        return ChatMessageResponse(
            conversation_id=conversation_id,
            content=execution.answer,
            agent_used=execution.agent,
            tool_calls=[
                ToolCallInfo(
                    tool_name=tc.get("tool_name", ""),
                    tool_input=tc.get("tool_input", {}),
                    tool_output=tc.get("tool_output"),
                )
                for tc in tool_calls_data
            ],
            execution=execution.model_dump(mode="json"),
        )

    # Resolve conversation
    # Load existing messages for context
    existing_messages = await _load_langchain_messages(db, conversation_id, owner_id)

    # Run the orchestrator pipeline
    attachment_paths = await _resolve_uploaded_paths(body.attachments, owner_id, db=db)
    result = await run_agent(
        user_input=body.content,
        conversation_id=conversation_id,
        attachments=attachment_paths,
        existing_messages=existing_messages,
        owner_id=owner_id,
    )

    # Extract response content
    assistant_content = _extract_response_content(result)
    agent_used = result.get("metadata", {}).get("agent_used")
    tool_calls_data = result.get("tool_calls", [])
    execution_metadata = result.get("metadata", {}).get("execution")

    # Persist user message
    user_msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=body.content,
    )
    db.add(user_msg)

    # Persist assistant message
    assistant_msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=assistant_content,
        agent_type=agent_used,
        execution_metadata=json.dumps(execution_metadata) if execution_metadata else None,
    )
    db.add(assistant_msg)
    await db.flush()

    # Persist tool call records
    for tc in tool_calls_data:
        record = ToolCallRecord(
            message_id=assistant_msg.id,
            tool_name=tc.get("tool_name", ""),
            tool_input=json.dumps(tc.get("tool_input", {})),
            tool_output=tc.get("tool_output"),
        )
        db.add(record)

    # Update conversation title from first user message
    if conversation.title == "New Conversation":
        conversation.title = body.content[:80].strip()

    await db.commit()

    logger.info(
        "chat_completed",
        conversation_id=conversation_id,
        agent_used=agent_used,
        tool_calls=len(tool_calls_data),
    )

    return ChatMessageResponse(
        conversation_id=conversation_id,
        content=assistant_content,
        agent_used=agent_used,
        execution=execution_metadata,
        tool_calls=[
            ToolCallInfo(
                tool_name=tc.get("tool_name", ""),
                tool_input=tc.get("tool_input", {}),
                tool_output=tc.get("tool_output"),
            )
            for tc in tool_calls_data
        ],
    )


# ---------------------------------------------------------------------------
# WebSocket /chat/stream — real-time streaming
# ---------------------------------------------------------------------------


@router.websocket("/chat/stream")
async def chat_stream(
    websocket: WebSocket,
    authenticated: AuthenticatedSession = Depends(get_websocket_session),  # noqa: B008
) -> None:
    """WebSocket endpoint for streaming chat responses.

    Protocol:
        Client sends: {"type": "message", "content": "...", "conversation_id": "...", "attachments": [...]}
        Server sends: {"type": "token"|"tool_call"|"tool_result"|"agent_switch"|"error"|"done", ...}

    A successful turn has one terminal ``done`` event. An agent failure has one
    terminal ``error`` event after persistence has finished; it never sends a
    subsequent ``done`` event. Persistence warnings for otherwise successful
    turns are carried in terminal ``done.metadata`` so they cannot replace the
    generated answer in the client.

    Persistence:
        After streaming completes, both the user message and the assembled
        assistant response are persisted to the application database, along
        with any tool call records. This mirrors the behavior of POST /chat.
    """
    await websocket.accept()
    logger.info("websocket_connected")
    owner_id = authenticated.account.id
    session_id = authenticated.session.id
    last_session_check = time.monotonic()

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=WEBSOCKET_SESSION_RECHECK_SECONDS
                )
            except TimeoutError:
                raw = None

            if raw is None or time.monotonic() - last_session_check >= (
                WEBSOCKET_SESSION_RECHECK_SECONDS
            ):
                if not await websocket_session_is_active(websocket, session_id):
                    await websocket.close(code=4401, reason="Session expired or revoked.")
                    return
                last_session_check = time.monotonic()
                if raw is None:
                    continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON message."})
                continue

            if not isinstance(data, dict):
                await websocket.send_json(
                    {"type": "error", "content": "Expected a message object."}
                )
                continue
            msg_type = data.get("type", "")
            if msg_type != "message":
                await websocket.send_json(
                    {"type": "error", "content": f"Unknown message type: {msg_type}"}
                )
                continue

            try:
                body = ChatMessageRequest.model_validate(data)
            except ValidationError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "Message content is required (maximum 32000 characters).",
                    }
                )
                continue
            content = body.content.strip()
            if not content:
                await websocket.send_json(
                    {"type": "error", "content": "Message content is required."}
                )
                continue

            conversation_id = body.conversation_id or str(uuid.uuid4())
            attachments = body.attachments

            # Accumulators for persistence after streaming completes
            token_chunks: list[str] = []
            tool_calls_data: list[dict] = []
            agent_used: str | None = None
            completion_metadata: dict[str, Any] = {}
            stream_failed = False
            stream_error = "Agent error: response failed. Check the backend and Ollama, then retry."
            execution_metadata: dict[str, Any] | None = None

            async def consume_event(
                event: dict[str, Any],
                chunks: list[str] = token_chunks,
                calls: list[dict] = tool_calls_data,
            ) -> None:
                nonlocal agent_used, completion_metadata, execution_metadata
                if event.get("type") != "done":
                    await websocket.send_json(event)
                evt_type = event.get("type")
                if evt_type == "token":
                    chunks.append(event.get("content", ""))
                elif evt_type == "tool_call":
                    calls.append(
                        {
                            "tool_name": event.get("tool", ""),
                            "tool_input": event.get("input", {}),
                            "tool_output": None,
                        }
                    )
                elif evt_type == "tool_result":
                    for tc in reversed(calls):
                        if tc["tool_name"] == event.get("tool", "") and tc["tool_output"] is None:
                            tc["tool_output"] = event.get("output")
                            break
                elif evt_type == "agent_switch":
                    agent_used = event.get("agent")
                elif evt_type == "done":
                    completion_metadata = event.get("metadata", {})
                    execution_metadata = completion_metadata.get("execution")
                    if agent_used is None:
                        agent_used = completion_metadata.get("agent_used")

            try:
                if body.agent_name:
                    selected = await _execute_selected_profile(
                        websocket.app,
                        body.model_copy(update={"conversation_id": conversation_id}),
                        owner_id=owner_id,
                        on_event=consume_event,
                    )
                    agent_used = selected.agent
                    selected_calls = selected.artifacts.get("tool_calls", [])
                    if selected_calls and not tool_calls_data:
                        for tc in selected_calls:
                            await consume_event(
                                {
                                    "type": "tool_call",
                                    "tool": tc.get("tool_name", ""),
                                    "input": tc.get("tool_input", {}),
                                }
                            )
                            await consume_event(
                                {
                                    "type": "tool_result",
                                    "tool": tc.get("tool_name", ""),
                                    "output": tc.get("tool_output"),
                                }
                            )
                    if not token_chunks:
                        await consume_event({"type": "token", "content": selected.answer})
                    execution_metadata = selected.model_dump(mode="json")
                    completion_metadata = {
                        "agent_used": selected.agent,
                        "execution": execution_metadata,
                    }
                else:
                    existing_messages = await _load_ws_history(conversation_id, owner_id)
                    attachment_paths = await _resolve_uploaded_paths(attachments, owner_id)
                    async for event in stream_agent(
                        user_input=content,
                        conversation_id=conversation_id,
                        attachments=attachment_paths,
                        existing_messages=existing_messages,
                        owner_id=owner_id,
                    ):
                        await consume_event(event)
            except HTTPException as exc:
                logger.info("profile_task_rejected", detail=exc.detail)
                stream_error = str(exc.detail)
                stream_failed = True
            except AppError as exc:
                stream_error = exc.message
                stream_failed = True
            except Exception:
                logger.exception("stream_error")
                # Keep the terminal error behind persistence. Sending it first
                # lets the client start another turn before the delayed
                # completion below, which can then reset that newer turn.
                stream_failed = True

            if time.monotonic() - last_session_check >= WEBSOCKET_SESSION_RECHECK_SECONDS:
                if not await websocket_session_is_active(websocket, session_id):
                    await websocket.close(code=4401, reason="Session expired or revoked.")
                    return
                last_session_check = time.monotonic()

            # Persist user + assistant messages to database
            assistant_content = "".join(token_chunks)
            saved = await _persist_ws_messages(
                conversation_id=conversation_id,
                owner_id=owner_id,
                user_content=content,
                assistant_content=assistant_content,
                agent_used=agent_used,
                tool_calls_data=tool_calls_data,
                execution_metadata=execution_metadata,
            )
            if stream_failed:
                # An agent failure has exactly one terminal event. In
                # particular, never follow this error with a done event.
                await websocket.send_json({"type": "error", "content": stream_error})
            else:
                if saved is False:
                    # The answer was generated successfully, so report the
                    # persistence problem as completion metadata rather than a
                    # second terminal error that would clear the answer.
                    completion_metadata = {
                        **completion_metadata,
                        "persistence_warning": "Could not save this conversation. Please retry.",
                    }
                await websocket.send_json(
                    {
                        "type": "done",
                        "metadata": {**completion_metadata, "conversation_id": conversation_id},
                    }
                )

    except WebSocketDisconnect:
        logger.info("websocket_disconnected")


# ---------------------------------------------------------------------------
# GET /chat/conversations — list conversations
# ---------------------------------------------------------------------------


@router.get("/chat/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> list[ConversationSummary]:
    """List all conversations ordered by most recent activity."""
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.owner_id == authenticated.account.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    return [
        ConversationSummary(
            id=conv.id,
            title=conv.title,
            message_count=len(conv.messages),
            last_message_at=conv.messages[-1].created_at if conv.messages else conv.created_at,
            created_at=conv.created_at,
        )
        for conv in conversations
    ]


# ---------------------------------------------------------------------------
# GET /chat/conversations/{conversation_id} — get conversation details
# ---------------------------------------------------------------------------


@router.get("/chat/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Get a conversation with all its messages and tool calls."""
    from app.api.middleware.error_handler import NotFoundError

    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages).selectinload(Message.tool_calls))
        .where(
            Conversation.id == conversation_id,
            Conversation.owner_id == authenticated.account.id,
        )
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise NotFoundError("Conversation", conversation_id)

    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "agent_type": msg.agent_type,
                "execution": json.loads(msg.execution_metadata) if msg.execution_metadata else None,
                "created_at": msg.created_at.isoformat(),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "tool_name": tc.tool_name,
                        "tool_input": json.loads(tc.tool_input) if tc.tool_input else {},
                        "tool_output": tc.tool_output,
                        "duration_ms": tc.duration_ms,
                    }
                    for tc in msg.tool_calls
                ],
            }
            for msg in conversation.messages
        ],
    }


# ---------------------------------------------------------------------------
# DELETE /chat/conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    authenticated: AuthenticatedSession = Depends(get_authenticated_session),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    """Delete a conversation and all its messages."""
    from app.api.middleware.error_handler import NotFoundError

    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.owner_id == authenticated.account.id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise NotFoundError("Conversation", conversation_id)

    await db.delete(conversation)
    await db.commit()

    return {"status": "deleted", "conversation_id": conversation_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _execute_selected_profile(
    app,
    body: ChatMessageRequest,
    *,
    owner_id: str,
    db: AsyncSession | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> AgentResult:
    """Dispatch an explicit chat profile through the shared registry and services."""
    registry = app.state.agent_registry
    profile = registry.get(body.agent_name or "")
    if profile is None:
        raise HTTPException(status_code=422, detail="Unknown or disabled agent profile.")
    if len(body.attachments) > 1:
        raise HTTPException(
            status_code=422, detail="Selected profiles accept one attachment at a time."
        )
    task = TaskRequest(
        prompt=body.content,
        agent_name=profile.name,
        collection=body.collection,
        symbol=body.symbol,
        workspace_path=body.workspace_path,
        context=body.context,
        workflow=body.workflow,
        inference=body.inference,
        asset_id=body.attachments[0] if body.attachments else None,
    )
    try:
        inference = registry.resolve_inference(profile, task)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if (
        profile.target in {"chat", "sql", "document", "web"}
        and profile.name != "document_analytics"
    ):
        conversation_id = body.conversation_id or str(uuid.uuid4())
        existing = []
        if body.conversation_id:
            existing = (
                await _load_langchain_messages(db, body.conversation_id, owner_id)
                if db is not None
                else await _load_ws_history(body.conversation_id, owner_id)
            )
        attachment_paths = await _resolve_uploaded_paths(body.attachments, owner_id, db=db)
        from app.agents.orchestrator import run_agent
        from app.services.llm import llm_service

        with llm_service.inference_context(inference):
            if on_event is None:
                state = await run_agent(
                    user_input=body.content,
                    conversation_id=conversation_id,
                    attachments=attachment_paths,
                    existing_messages=existing,
                    forced_agent=profile.target,
                    owner_id=owner_id,
                )
            else:
                state = None
                async for event in stream_agent(
                    user_input=body.content,
                    conversation_id=conversation_id,
                    attachments=attachment_paths,
                    existing_messages=existing,
                    forced_agent=profile.target,
                    owner_id=owner_id,
                ):
                    if event.get("type") == "done":
                        state = event.get("state")
                    else:
                        await on_event(event)
                if state is None:
                    raise RuntimeError("Agent stream did not return a final state.")
        metadata = state.get("metadata", {})
        return AgentResult(
            agent=profile.name,
            answer=_extract_response_content(state),
            artifacts={
                **({"retrieval": metadata["retrieval"]} if metadata.get("retrieval") else {}),
                **({"tool_calls": state["tool_calls"]} if state.get("tool_calls") else {}),
            },
            metadata=ExecutionMetadata(
                request_id=str(uuid.uuid4()),
                target=profile.target,
                agent_name=profile.name,
                model=inference.model,
                inference=inference,
            ),
        )

    prior_turns = []
    if body.conversation_id:
        history = (
            await _load_langchain_messages(db, body.conversation_id, owner_id)
            if db is not None
            else await _load_ws_history(body.conversation_id, owner_id)
        )
        prior_turns = [
            f"{message.type}: {str(message.content)[:1200]}"
            for message in history[-8:]
            if getattr(message, "content", None)
        ]
        if prior_turns and profile.target != "rag":
            history_header = "Prior conversation:\n"
            current_request = "\n\nCurrent request:\n" + body.content
            history_limit = max(0, 32_000 - len(history_header) - len(current_request) - 1)
            history = "\n".join(prior_turns)[-history_limit:] if history_limit else ""
            task.prompt = (
                f"{history_header}{history}\n{current_request}" if history_limit else body.content
            )

    document = None
    if task.asset_id:
        documents = await _load_uploaded_documents([task.asset_id], owner_id, db=db)
        document = documents.get(task.asset_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Uploaded asset was not found.")
    kwargs = {"history": prior_turns} if profile.target == "rag" else {}
    if on_event is not None:

        async def emit_token(text: str) -> None:
            await on_event({"type": "token", "content": text})

        kwargs["on_token"] = emit_token
    return await app.state.task_runner.run(
        task,
        request_id=str(uuid.uuid4()),
        document=document,
        owner_id=owner_id,
        **kwargs,
    )


async def _load_uploaded_documents(
    attachment_ids: list[str], owner_id: str, *, db: AsyncSession | None = None
) -> dict[str, Document]:
    """Resolve only IDs created by the upload route to trusted document records."""
    if not attachment_ids:
        return {}
    if db is not None:
        result = await db.execute(
            select(Document).where(Document.id.in_(attachment_ids), Document.owner_id == owner_id)
        )
        return {document.id: document for document in result.scalars().all()}
    from app.services.database import get_app_session_factory

    async with get_app_session_factory()() as session:
        result = await session.execute(
            select(Document).where(Document.id.in_(attachment_ids), Document.owner_id == owner_id)
        )
        return {document.id: document for document in result.scalars().all()}


async def _resolve_uploaded_paths(
    attachment_ids: list[str], owner_id: str, *, db: AsyncSession | None = None
) -> list[str]:
    if not attachment_ids:
        return []
    documents = await _load_uploaded_documents(attachment_ids, owner_id, db=db)
    if len(documents) != len(set(attachment_ids)):
        raise HTTPException(status_code=404, detail="One or more uploaded assets were not found.")
    return [documents[attachment_id].storage_path for attachment_id in attachment_ids]


async def _load_ws_history(conversation_id: str, owner_id: str) -> list:
    """Load history in a short-lived session before a streaming turn."""
    from app.services.database import get_app_session_factory

    async with get_app_session_factory()() as db:
        await _get_or_create_conversation(db, conversation_id, owner_id)
        return await _load_langchain_messages(db, conversation_id, owner_id)


async def _persist_ws_messages(
    conversation_id: str,
    owner_id: str,
    user_content: str,
    assistant_content: str,
    agent_used: str | None,
    tool_calls_data: list[dict],
    execution_metadata: dict[str, Any] | None = None,
) -> bool:
    """Persist user and assistant messages from a WebSocket stream to the DB.

    Opens its own database session (WebSocket endpoints don't participate
    in FastAPI's ``Depends`` lifecycle). Failures are logged but never
    raised so that a transient DB error doesn't crash the chat stream.
    Returns whether saving succeeded, allowing the route to report failures.

    Args:
        conversation_id: The conversation to write to (created if missing).
        user_content: The original user message text.
        assistant_content: The assembled assistant response (concatenated tokens).
        agent_used: Which agent handled the message, if known.
        tool_calls_data: List of tool call dicts with tool_name/tool_input/tool_output.
    """
    from app.services.database import get_app_session_factory

    try:
        factory = get_app_session_factory()
        async with factory() as db:
            conversation = await _get_or_create_conversation(db, conversation_id, owner_id)

            # Persist user message
            user_msg = Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=user_content,
            )
            db.add(user_msg)

            # Persist assistant message
            assistant_msg = Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=assistant_content or "No response generated.",
                agent_type=agent_used,
                execution_metadata=json.dumps(execution_metadata) if execution_metadata else None,
            )
            db.add(assistant_msg)
            await db.flush()

            # Persist tool call records
            for tc in tool_calls_data:
                record = ToolCallRecord(
                    message_id=assistant_msg.id,
                    tool_name=tc.get("tool_name", ""),
                    tool_input=json.dumps(tc.get("tool_input", {})),
                    tool_output=tc.get("tool_output"),
                )
                db.add(record)

            # Update conversation title from first user message
            if conversation.title == "New Conversation":
                conversation.title = user_content[:80].strip()

            await db.commit()

        logger.info(
            "ws_messages_persisted",
            conversation_id=conversation_id,
            agent_used=agent_used,
            tool_calls=len(tool_calls_data),
        )
        return True
    except Exception as exc:
        logger.error(
            "ws_persistence_failed",
            conversation_id=conversation_id,
            error=str(exc),
            exc_info=True,
        )
        return False


async def _get_or_create_conversation(
    db: AsyncSession, conversation_id: str, owner_id: str
) -> Conversation:
    """Get an owned conversation or create one; hide other owners' IDs as not found."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if conversation is not None and conversation.owner_id != owner_id:
        from app.api.middleware.error_handler import NotFoundError

        raise NotFoundError("Conversation", conversation_id)
    if conversation is None:
        conversation = Conversation(id=conversation_id, owner_id=owner_id)
        db.add(conversation)
        await db.flush()

    return conversation


async def _load_langchain_messages(db: AsyncSession, conversation_id: str, owner_id: str) -> list:
    """Load prior messages from the DB and convert to LangChain message objects.

    Returns an empty list if no prior messages exist.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.conversation_id == conversation_id,
            Conversation.owner_id == owner_id,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )
    result = await db.execute(stmt)
    recent_messages = list(reversed(result.scalars().all()))

    messages = []
    context_characters = 0
    for message in reversed(recent_messages):
        if context_characters + len(message.content) > MAX_CONTEXT_CHARACTERS:
            break
        messages.append(message)
        context_characters += len(message.content)
    messages.reverse()

    lc_messages = []
    for msg in messages:
        if msg.role == MessageRole.USER:
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == MessageRole.ASSISTANT:
            lc_messages.append(AIMessage(content=msg.content))
        elif msg.role == MessageRole.SYSTEM:
            lc_messages.append(SystemMessage(content=msg.content))
        # Skip tool messages for now — they're ephemeral
    return lc_messages


def _extract_response_content(result: dict[str, Any]) -> str:
    """Extract the assistant's text response from the final AgentState."""
    messages = result.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content"):
            return str(last_msg.content)
    return "I'm sorry, I wasn't able to generate a response."
