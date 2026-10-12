"""Profile-aware specialist execution for bounded, uploaded-file tasks."""

from __future__ import annotations

import asyncio
import base64
import json
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
from app.services.workspace import WorkspaceInputError, read_workspace

if TYPE_CHECKING:
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

    async def run(
        self,
        request: TaskRequest,
        *,
        request_id: str,
        document: Document | None = None,
    ) -> AgentResult:
        execution = self._resolve_execution(request, document)
        target = execution.profile.target
        if target == "image_analysis":
            result = await self._image_analysis(request, execution, document)
        elif target == "image_fraud":
            result = await self._image_fraud(execution, document)
        elif target == "document":
            result = await self._document_analysis(request, execution, document)
        elif target == "rag":
            result = await self._rag_answer(request, execution)
        elif target == "stock_research":
            result = await self._stock_research(request, execution, document)
        elif target == "image_generation":
            result = await self._image_generation(request, execution)
        elif target == "software_engineer":
            result = await self._software_review(request, execution)
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
        return result.model_copy(update={"metadata": metadata})

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
        self, request: TaskRequest, execution: AgentExecution
    ) -> AgentResult:
        from app.services.hybrid_vector_store import hybrid_vector_store_service

        try:
            search = await hybrid_vector_store_service.search_with_provenance(
                query=request.prompt,
                collection=request.collection,
                top_k=settings.rag_top_k,
                agent_name=execution.profile.name,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=f"Hybrid retrieval failed: {exc}") from exc
        passages = search.passages
        if not passages:
            return AgentResult(
                agent=execution.profile.name,
                answer="I could not find relevant evidence in the selected collection.",
                artifacts={"citations": [], "retrieval": search.retrieval},
                limitations=["No supporting passages were retrieved."],
            )
        citation_rows = []
        prompt_rows = []
        for passage in passages:
            metadata = passage.get("metadata", {})
            citation = {
                key: metadata.get(key)
                for key in (
                    "filename",
                    "source",
                    "page",
                    "page_start",
                    "page_end",
                    "section",
                    "document_id",
                    "source_chunk_id",
                )
                if metadata.get(key) is not None
            }
            citation["score"] = passage.get("score")
            citation["score_type"] = passage.get("score_type")
            citation_rows.append(citation)
            source = citation.get("filename") or citation.get("source") or citation.get("document_id") or "Unknown"
            location = f", Page {citation['page']}" if citation.get("page") is not None else ""
            chunk_id = citation.get("source_chunk_id") or citation.get("document_id")
            prompt_rows.append(
                f"[Source: {source}{location}; chunk: {chunk_id}]\n{passage.get('content', '')}"
            )
        answer = await self._answer(
            execution,
            prompt_values={"prompt": request.prompt, "passages": "\n\n".join(prompt_rows)},
        )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={"citations": citation_rows, "retrieval": search.retrieval},
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
        return AgentResult(agent=execution.profile.name, answer=answer, artifacts=artifacts)

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
        self, request: TaskRequest, execution: AgentExecution
    ) -> AgentResult:
        try:
            workspace, sources = await asyncio.to_thread(
                read_workspace, settings.agent_workspace_root, request.workspace_path
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
            response = await model.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=human_content)]
            )
        return str(response.content)

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
