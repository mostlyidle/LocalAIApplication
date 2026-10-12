"""Profile-aware specialist execution for bounded, uploaded-file tasks."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.registry import AgentExecution, AgentRegistry
from app.models.enums import DocumentFormat
from app.models.profile_schemas import AgentResult, ExecutionMetadata, TaskRequest
from app.services.document_parser import DocumentParserService
from app.services.images import ImageInspectionError, inspect_image, manipulation_signals
from app.services.llm import llm_service

if TYPE_CHECKING:
    from app.models.db_models import Document
    from app.prompt_store import PromptStore


class TaskRunner:
    """Run one named specialist using LocalAI's parser, uploads, and profile catalog."""

    def __init__(self, registry: AgentRegistry, prompts: PromptStore) -> None:
        self._registry = registry
        self._prompts = prompts
        self._parser = DocumentParserService()

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
