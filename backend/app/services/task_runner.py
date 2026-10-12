"""Profile-aware specialist execution for bounded, uploaded-file tasks."""

from __future__ import annotations

import asyncio
import base64
import json
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.registry import AgentExecution, AgentRegistry
from app.config import settings
from app.models.enums import DocumentFormat
from app.models.profile_schemas import AgentResult, ExecutionMetadata, TaskRequest
from app.services.document_parser import DocumentParserService
from app.services.images import ImageInspectionError, inspect_image, manipulation_signals
from app.services.llm import llm_service
from app.services.market_data import MarketDataError
from app.services.workspace import WorkspaceInputError, account_workspace_root, read_workspace

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.models.db_models import Document
    from app.prompt_store import PromptStore
    from app.services.comfyui import ComfyUIClient
    from app.services.market_data import FinnhubMarketDataClient


class TaskRunner:
    """Run one named specialist using LocalAI's parser, uploads, and profile catalog."""

    def __init__(
        self,
        registry: AgentRegistry,
        prompts: PromptStore,
        *,
        market_data: FinnhubMarketDataClient,
        comfyui: ComfyUIClient,
    ) -> None:
        self._registry = registry
        self._prompts = prompts
        self._parser = DocumentParserService()
        self._market_data = market_data
        self._comfyui = comfyui
        self._on_token: ContextVar[Callable[[str], Awaitable[None]] | None] = ContextVar(
            "task_tokens", default=None
        )
        self._memory_context: ContextVar[str] = ContextVar("task_memory_context", default="")

    async def run(
        self,
        request: TaskRequest,
        *,
        request_id: str,
        document: Document | None = None,
        history: list[str] | None = None,
        owner_id: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentResult:
        token = self._on_token.set(on_token)
        memory_token = self._memory_context.set("")
        try:
            execution = self._resolve_execution(request, document)
            target = execution.profile.target
            if owner_id and target in {
                "image_analysis",
                "document",
                "stock_research",
                "software_engineer",
            }:
                from app.services.memory_context import load_account_memory_context

                self._memory_context.set(
                    await load_account_memory_context(owner_id, query=request.prompt)
                )
            if target == "image_analysis":
                result = await self._image_analysis(request, execution, document)
            elif target == "image_fraud":
                result = await self._image_fraud(execution, document)
            elif target == "document":
                result = await self._document_analysis(request, execution, document)
            elif target == "rag":
                result = await self._rag_answer(
                    request, execution, history=history, owner_id=owner_id
                )
            elif target == "stock_research":
                result = await self._stock_research(request, execution, document)
            elif target == "image_generation":
                result = await self._image_generation(request, execution)
            elif target == "software_engineer":
                result = await self._software_review(request, execution, owner_id=owner_id)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"The '{execution.profile.name}' specialist is not available yet.",
                )
            inference = execution.inference
            metadata = ExecutionMetadata(
                request_id=request_id,
                target=target,
                agent_name=execution.profile.name,
                model=inference.model if inference else None,
                inference=inference,
            )
            from app.services.memory_context import memory_sources_from_context

            memory_sources = memory_sources_from_context(self._memory_context.get())
            artifacts = dict(result.artifacts)
            if memory_sources:
                artifacts["memory_sources"] = memory_sources
            return result.model_copy(update={"metadata": metadata, "artifacts": artifacts})
        finally:
            self._on_token.reset(token)
            self._memory_context.reset(memory_token)

    def _resolve_execution(self, request: TaskRequest, document: Document | None) -> AgentExecution:
        profile = self._registry.get(request.agent_name) if request.agent_name else None
        if request.agent_name and profile is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown or disabled agent_name '{request.agent_name}'.",
            )
        if profile is None:
            target = request.target
            if target == "auto":
                if request.workflow:
                    target = "image_generation"
                elif request.symbol:
                    target = "stock_research"
                elif request.workspace_path:
                    target = "software_engineer"
                elif document is not None and DocumentFormat(document.format).is_image:
                    target = "image_analysis"
                elif document is not None:
                    target = "document"
                else:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Select a specialist or provide a supported specialist input.",
                    )
            profile = self._registry.default_for(target)
        if request.target != "auto" and request.target != profile.target:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="agent_name does not match the requested target.",
            )
        try:
            inference = self._registry.resolve_inference(profile, request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return AgentExecution(profile=profile, inference=inference)

    async def _image_analysis(
        self, request: TaskRequest, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        path = self._uploaded_path(document, image=True)
        try:
            metadata = await asyncio.to_thread(inspect_image, path)
            image_data = await asyncio.to_thread(path.read_bytes)
        except (OSError, ImageInspectionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        answer = await self._answer(
            execution,
            prompt_values={"prompt": request.prompt},
            image_bytes=image_data,
            image_format=str(metadata.get("format") or "PNG").lower(),
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={"asset_id": document.id, **metadata},
        )

    async def _image_fraud(
        self, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        path = self._uploaded_path(document, image=True)
        try:
            inspection = await asyncio.to_thread(manipulation_signals, path)
        except (OSError, ImageInspectionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        signals = inspection["signals"]
        answer = "Forensic screening completed. " + (
            " ".join(signals)
            if signals
            else "No simple metadata or recompression anomaly was found."
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={"asset_id": document.id, **inspection},
            limitations=[
                "These are triage signals, not proof of authenticity or fraud.",
                "Use a validated forensic model and human review for consequential decisions.",
            ],
        )

    async def _document_analysis(
        self, request: TaskRequest, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        content = request.context or ""
        artifacts: dict[str, object] = {}
        if document is not None:
            path = Path(document.storage_path)
            try:
                parsed = await self._parser.parse(path, DocumentFormat(document.format))
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Could not parse document: {exc}",
                ) from exc
            content = parsed.text
            artifacts = {"asset_id": document.id, "filename": document.filename}
        if not content.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide an uploaded document or non-empty context for analysis.",
            )
        answer = await self._answer(
            execution,
            prompt_values={"prompt": request.prompt, "content": content[:30_000]},
        )
        return AgentResult(agent=execution.profile.name, answer=answer, artifacts=artifacts)

    async def _rag_answer(
        self,
        request: TaskRequest,
        execution: AgentExecution,
        *,
        history: list[str] | None = None,
        owner_id: str | None = None,
    ) -> AgentResult:
        from app.services.rag_context import prepare_rag_context

        context = await prepare_rag_context(
            request, execution, self._prompts, history=history, owner_id=owner_id
        )
        answer = (
            await self._answer(execution, prompt_values=context.prompt_values)
            if context.citations
            else "I could not find relevant evidence in the selected collection."
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={"citations": context.citations, "retrieval": context.retrieval},
            limitations=context.limitations,
        )

    async def _stock_research(
        self, request: TaskRequest, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        if not request.symbol:
            raise HTTPException(status_code=422, detail="Provide a ticker symbol.")
        try:
            snapshot = await self._market_data.snapshot(request.symbol)
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        material = request.context or ""
        artifacts: dict[str, object] = {"market_data": snapshot}
        if document is not None:
            try:
                parsed = await self._parser.parse(
                    Path(document.storage_path), DocumentFormat(document.format)
                )
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=422, detail=f"Could not parse document: {exc}"
                ) from exc
            material = f"{material}\n\n{parsed.text}".strip()
            artifacts["source_document"] = {
                "asset_id": document.id,
                "filename": document.filename,
            }
        answer = await self._answer(
            execution,
            prompt_values={
                "prompt": request.prompt,
                "symbol": request.symbol.upper(),
                "live_data": json.dumps(snapshot, ensure_ascii=False),
                "context": material[:30_000],
            },
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts=artifacts,
            limitations=snapshot.get("warnings", []),
        )

    async def _image_generation(
        self, request: TaskRequest, execution: AgentExecution
    ) -> AgentResult:
        workflow = request.workflow
        if not workflow:
            raise HTTPException(status_code=422, detail="Provide a ComfyUI workflow.")
        if len(json.dumps(workflow, ensure_ascii=False).encode("utf-8")) > 1_000_000:
            raise HTTPException(status_code=413, detail="The workflow exceeds the 1 MB limit.")
        try:
            submission = await self._comfyui.submit(workflow)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return AgentResult(
            agent=execution.profile.name,
            answer="Workflow submitted to local ComfyUI.",
            artifacts={"prompt_id": submission["prompt_id"]},
            limitations=["Image generation runs in ComfyUI; retrieve outputs there."],
        )

    async def _software_review(
        self, request: TaskRequest, execution: AgentExecution, *, owner_id: str | None
    ) -> AgentResult:
        try:
            workspace_root = account_workspace_root(settings.agent_workspace_root, owner_id)
            workspace, sources = await asyncio.to_thread(
                read_workspace, workspace_root, request.workspace_path
            )
        except WorkspaceInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        answer = await self._answer(
            execution,
            prompt_values={
                "prompt": request.prompt,
                "workspace_root": request.workspace_path or ".",
                "excerpts": workspace,
            },
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={"source_files": sources},
            limitations=[
                "Review used a bounded read-only sample of supported text files.",
                "No files were modified or commands executed.",
            ],
        )

    async def _answer(
        self,
        execution: AgentExecution,
        *,
        prompt_values: dict[str, object],
        image_bytes: bytes | None = None,
        image_format: str | None = None,
    ) -> str:
        inference = execution.inference
        if inference is None:
            raise RuntimeError(f"Agent '{execution.profile.name}' has no inference configuration.")
        target = execution.profile.target
        system, prompt = self._prompts.render_messages(
            execution.profile.name,
            target,
            {"agent_name": execution.profile.name, "target": target, **prompt_values},
        )
        human_content: str | list[dict[str, object]] = prompt
        if image_bytes is not None:
            image_data = base64.b64encode(image_bytes).decode("ascii")
            mime = "jpeg" if image_format in {"jpg", "jpeg"} else image_format or "png"
            human_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": f"data:image/{mime};base64,{image_data}",
                },
            ]
        with llm_service.inference_context(inference):
            model = llm_service.get_chat_model(
                model=inference.model,
                temperature=inference.temperature,
                max_tokens=inference.max_output_tokens,
                num_ctx=inference.context_window,
            )
            messages = [SystemMessage(content=system)]
            memory_context = self._memory_context.get()
            if memory_context:
                from app.agents.memory_context import MEMORY_CONTEXT_INSTRUCTIONS

                messages.append(
                    SystemMessage(content=f"{MEMORY_CONTEXT_INSTRUCTIONS}\n{memory_context}")
                )
            messages.append(HumanMessage(content=human_content))
            on_token = self._on_token.get()
            if on_token is None:
                response = await model.ainvoke(messages)
                return str(response.content)
            chunks: list[str] = []
            async for chunk in model.astream(messages):
                if chunk.content:
                    text = str(chunk.content)
                    chunks.append(text)
                    await on_token(text)
            return "".join(chunks)

    @staticmethod
    def _uploaded_path(document: Document | None, *, image: bool) -> Path:
        if document is None:
            required = "an uploaded image" if image else "an uploaded document"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"This specialist requires {required} asset_id.",
            )
        if image and not DocumentFormat(document.format).is_image:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The selected asset is not an image.",
            )
        return Path(document.storage_path)
