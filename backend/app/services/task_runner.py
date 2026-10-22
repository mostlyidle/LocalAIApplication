"""Profile-aware specialist execution for bounded, uploaded-file tasks."""

from __future__ import annotations

import asyncio
import base64
import json
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.registry import AgentExecution, AgentRegistry
from app.config import settings
from app.models.enums import DocumentFormat
from app.models.profile_schemas import AgentResult, ExecutionMetadata, TaskRequest
from app.services.document_parser import DocumentParserService
from app.services.images import ImageInspectionError, inspect_image, manipulation_signals
from app.services.llm import llm_service
from app.services.market_data import MarketDataError
from app.services.medical_lab import (
    MAX_INTERPRETATION_CONTEXT_CHARS,
    MEDICAL_LAB_PROFILE,
    add_local_ocr,
    assemble_lab_results,
    extract_report_alerts,
    parse_page_observations,
    prepare_lab_pages,
    render_lab_answer,
)
from app.services.spreadsheet import (
    SpreadsheetError,
    SpreadsheetPlan,
    execute_plan,
    load_spreadsheet,
)
from app.services.workspace import WorkspaceInputError, account_workspace_root, read_workspace

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.models.db_models import Document
    from app.prompt_store import PromptStore
    from app.services.comfyui import ComfyUIClient
    from app.services.market_data import FinnhubMarketDataClient


def _strip_model_thinking(answer: str) -> str:
    """Remove Gemma thinking-channel text accidentally returned as user-facing content."""
    start_marker = "<unused94>thought"
    end_marker = "<unused95>"
    start = answer.find(start_marker)
    if start < 0:
        return answer.strip()
    end = answer.find(end_marker, start + len(start_marker))
    if end < 0:
        return answer[:start].strip()
    return (answer[:start] + answer[end + len(end_marker) :]).strip()


def _render_spreadsheet_answer(prompt: str, result: dict[str, object]) -> str:
    headers = result["headers"]
    rows = result["rows"]
    evidence = result["source_rows"]
    assert isinstance(headers, list) and isinstance(rows, list) and isinstance(evidence, list)
    if not rows:
        return f"No rows matched the request: {prompt}"

    def escape(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    display_headers = [*headers, "Source rows"]
    lines = [
        f"Found {result['matched_rows']} matching source rows for: {escape(prompt)}",
        "",
        "| " + " | ".join(escape(header) for header in display_headers) + " |",
        "| " + " | ".join("---" for _ in display_headers) + " |",
    ]
    for row, source_rows in zip(rows[:20], evidence[:20], strict=True):
        values = [str(row.get(header, "")) for header in headers]
        values.append(", ".join(map(str, source_rows)))
        lines.append("| " + " | ".join(escape(value) for value in values) + " |")
    return "\n".join(lines)


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
            if (
                owner_id
                and target
                in {
                    "image_analysis",
                    "document",
                    "rag",
                    "stock_research",
                    "software_engineer",
                }
                and execution.profile.name != MEDICAL_LAB_PROFILE
            ):
                from app.services.memory_context import load_account_memory_context

                self._memory_context.set(
                    await load_account_memory_context(owner_id, query=request.prompt)
                )
            if target == "image_analysis":
                result = await self._image_analysis(request, execution, document)
            elif target == "image_fraud":
                result = await self._image_fraud(execution, document)
            elif target == "document":
                if execution.profile.name == MEDICAL_LAB_PROFILE:
                    result = await self._medical_lab_analysis(request, execution, document)
                else:
                    result = await self._document_analysis(request, execution, document)
            elif target == "spreadsheet":
                result = await self._spreadsheet_analysis(request, execution, document)
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
                elif document is not None and DocumentFormat(document.format) in {
                    DocumentFormat.CSV,
                    DocumentFormat.XLSX,
                }:
                    target = "spreadsheet"
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

    async def _spreadsheet_analysis(
        self, request: TaskRequest, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        if document is None:
            raise HTTPException(
                status_code=422, detail="Attach one CSV or XLSX file for spreadsheet analysis."
            )
        if document.format not in {DocumentFormat.CSV.value, DocumentFormat.XLSX.value}:
            raise HTTPException(status_code=422, detail="Only CSV and XLSX files are supported.")
        try:
            table = await asyncio.to_thread(
                load_spreadsheet, Path(document.storage_path), document.format
            )
        except (OSError, SpreadsheetError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        inference = execution.inference
        if inference is None:
            raise RuntimeError("Spreadsheet profile has no inference configuration.")
        sample_headers = table["headers"][:10]
        sample = [
            {header: row[header][:100] for header in sample_headers} for row in table["rows"][:3]
        ]
        values = {
            "prompt": request.prompt[:4_000],
            "table_summary": json.dumps(
                {
                    "headers": table["headers"],
                    "column_types": table["column_types"],
                    "sample_rows": sample,
                    "sheet": table["sheet"],
                    "available_sheets": table["available_sheets"],
                },
                ensure_ascii=False,
            ),
        }
        system, prompt = self._prompts.render_messages(
            execution.profile.name, execution.profile.target, values
        )
        try:
            with llm_service.inference_context(inference.model_copy(update={"temperature": 0})):
                model = llm_service.get_chat_model(
                    model=inference.model,
                    temperature=0,
                    max_tokens=inference.max_output_tokens,
                    num_ctx=inference.context_window,
                )
                raw_plan = await model.with_structured_output(SpreadsheetPlan).ainvoke(
                    [SystemMessage(content=system), HumanMessage(content=prompt)]
                )
            plan = (
                raw_plan
                if isinstance(raw_plan, SpreadsheetPlan)
                else SpreadsheetPlan.model_validate(raw_plan)
            )
            if not plan.supported:
                return AgentResult(
                    agent=execution.profile.name,
                    answer="I couldn't safely translate that request into a supported spreadsheet operation.",
                    artifacts={"asset_id": document.id, "filename": document.filename},
                    limitations=[
                        "Try asking for filtering, sorting, grouping, or a numeric aggregate."
                    ],
                )
            result = await asyncio.to_thread(execute_plan, table, plan)
        except (OutputParserException, ValidationError, TypeError, ValueError):
            return AgentResult(
                agent=execution.profile.name,
                answer="I couldn't safely translate that request into a supported spreadsheet operation.",
                artifacts={"asset_id": document.id, "filename": document.filename},
                limitations=[
                    "Try asking for filtering, sorting, grouping, or a numeric aggregate."
                ],
            )

        answer = _render_spreadsheet_answer(request.prompt, result)
        if table["sheet"]:
            answer = f"Sheet: {table['sheet']}\n\n{answer}"
        limitations: list[str] = []
        if result["evidence_truncated"]:
            limitations.append("Source row evidence is capped at 20 rows per result group.")
        if result["cells_truncated"]:
            limitations.append("Displayed cell values are capped at 500 characters.")
        if len(result["rows"]) > 20:
            limitations.append(
                "The chat answer shows the first 20 rows; the result artifact contains all returned rows."
            )
        if result["result_count"] > len(result["rows"]):
            limitations.append(
                f"Showing {len(result['rows'])} of {result['result_count']} result rows."
            )
        if document.format == DocumentFormat.XLSX.value:
            limitations.append(
                "XLSX formulas use cached values from the last spreadsheet recalculation; formulas are not evaluated."
            )
        return AgentResult(
            agent=execution.profile.name,
            answer=answer,
            artifacts={
                "asset_id": document.id,
                "filename": document.filename,
                "sheet": table["sheet"],
                "available_sheets": table["available_sheets"],
                "row_count": len(table["rows"]),
                "matched_rows": result["matched_rows"],
                "headers": result["headers"],
                "rows": result["rows"],
                "source_rows": result["source_rows"],
            },
            limitations=limitations,
        )

    async def _medical_lab_analysis(
        self, request: TaskRequest, execution: AgentExecution, document: Document | None
    ) -> AgentResult:
        parsed = None
        file_path = None
        doc_format = None
        artifacts: dict[str, object] = {}
        if document is not None:
            file_path = Path(document.storage_path)
            doc_format = DocumentFormat(document.format)
            try:
                parsed = await self._parser.parse(file_path, doc_format)
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Could not parse lab report: {exc}",
                ) from exc
            artifacts = {"asset_id": document.id, "filename": document.filename}

        vision = execution.inference is not None and execution.inference.model == "medgemma1.5:4b"
        try:
            pages = await asyncio.to_thread(
                prepare_lab_pages,
                file_path,
                doc_format,
                parsed,
                vision=vision,
                pasted_text=request.context or request.prompt,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        observations: list[dict[str, object]] = []
        report_alerts: list[dict[str, object]] = []
        skipped_pages: list[int] = []
        invalid_pages: list[int] = []
        truncated_pages: list[int] = []
        analyzed_pages = []
        for page in pages:
            if vision:
                page = await add_local_ocr(page)
            analyzed_pages.append(page)
            report_alerts.extend(extract_report_alerts([page]))
            if page.truncated:
                truncated_pages.append(page.number)
            if not page.text.strip() and page.image_bytes is None:
                skipped_pages.append(page.number)
                continue
            raw = await self._answer(
                execution,
                prompt_values={
                    "prompt": request.prompt,
                    "page_number": page.number,
                    "content": page.text,
                    "source_kind": "image with local text extraction"
                    if page.image_bytes
                    else "text",
                },
                image_bytes=page.image_bytes,
                image_format=page.image_format,
                stream=False,
            )
            page_observations, valid = parse_page_observations(raw, page)
            observations.extend(page_observations)
            if not valid:
                invalid_pages.append(page.number)

        results = assemble_lab_results(observations)
        full_report_context = "\n\n".join(
            f"Page {page.number}:\n{page.text}" for page in analyzed_pages if page.text.strip()
        )
        report_context_truncated = len(full_report_context) > MAX_INTERPRETATION_CONTEXT_CHARS
        report_context = full_report_context[:MAX_INTERPRETATION_CONTEXT_CHARS]
        limitations = [
            "Diagnosis and treatment advice are AI-generated, unvalidated, and may be wrong; have a qualified clinician confirm them and do not change medication based on this response.",
            "Numeric comparisons require an exact source-text match, a clear numeric result and interval, and matching units. No unit conversions are performed.",
            "Cross-page fields are joined only by a unique normalized test name and unit; conflicting or incomplete matches are left for review.",
            "Image and scanned-page values still require checking against the uploaded report, even when local OCR text matches.",
        ]
        if skipped_pages:
            limitations.append(
                "The selected text-only model could not read pages without extracted text: "
                + ", ".join(map(str, skipped_pages))
                + "."
            )
        if invalid_pages:
            limitations.append(
                "Structured extraction failed on pages: "
                + ", ".join(map(str, invalid_pages))
                + "; no values from those pages were compared."
            )
        if truncated_pages:
            limitations.append(
                "Text extraction was limited to 12,000 characters on pages: "
                + ", ".join(map(str, truncated_pages))
                + "; comparisons from those pages were withheld."
            )
        if report_context_truncated:
            limitations.append(
                "Report context for diagnosis and treatment advice was limited to the first "
                f"{MAX_INTERPRETATION_CONTEXT_CHARS:,} characters."
            )
        verified_findings = [
            {
                "test_name": result["test_name"],
                "result": result["result"],
                "unit": result["unit"],
                "reference_interval": result["reference_interval"],
                "reference_qualifier": result["reference_qualifier"],
                "comparison": result["comparison"],
                "comparison_reason": result["comparison_reason"],
                "report_flags": [
                    flag["text"] for flag in result["report_flags"] if flag["verified"]
                ],
                "sources": [
                    {
                        "page": source["page"],
                        "excerpt": str(source["excerpt"] or "")[:120],
                    }
                    for source in result["sources"][:2]
                ],
            }
            for result in results
            if result["sources"] and all(source["verified"] for source in result["sources"])
        ][:15]
        interpretation = None
        if verified_findings:
            interpretation = await self._answer(
                execution,
                purpose="interpretation",
                prompt_values={
                    "prompt": request.prompt[:1_600],
                    "findings": json.dumps(verified_findings, ensure_ascii=False),
                    "report_context": report_context,
                    "report_context_truncated": report_context_truncated,
                    "report_alerts": json.dumps(report_alerts[:10], ensure_ascii=False),
                    "omitted_count": max(0, len(results) - len(verified_findings)),
                },
                stream=False,
            )
            interpretation = _strip_model_thinking(interpretation)

        artifacts.update(
            {
                "tests": results,
                "extraction_pages": len(pages),
                "skipped_pages": skipped_pages,
                "invalid_pages": invalid_pages,
                "truncated_pages": truncated_pages,
                "report_alerts": report_alerts,
                "interpretation_findings": len(verified_findings),
            }
        )
        if not verified_findings:
            limitations.append(
                "No source-verified findings were available, so the model did not generate diagnosis or treatment advice."
            )
        elif len(verified_findings) < len(results):
            limitations.append(
                "Some extracted rows were omitted because source evidence was missing or the model input was capped; review all extracted rows."
            )
        return AgentResult(
            agent=execution.profile.name,
            answer=render_lab_answer(results, report_alerts, interpretation),
            artifacts=artifacts,
            limitations=limitations,
        )

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
            request,
            execution,
            self._prompts,
            history=history,
            owner_id=owner_id,
            memory_context=self._memory_context.get(),
        )
        self._memory_context.set(context.memory_context)
        answer = (
            context.answer_override
            if context.answer_override is not None
            else (
                await self._answer(execution, prompt_values=context.prompt_values)
                if context.citations
                else "I could not find relevant evidence in the selected collection."
            )
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
        purpose: str | None = None,
        image_bytes: bytes | None = None,
        image_format: str | None = None,
        stream: bool = True,
    ) -> str:
        inference = execution.inference
        if inference is None:
            raise RuntimeError(f"Agent '{execution.profile.name}' has no inference configuration.")
        target = execution.profile.target
        values = {"agent_name": execution.profile.name, "target": target, **prompt_values}
        if purpose:
            system, prompt = self._prompts.render_messages_for(
                execution.profile.name, target, purpose, values
            )
        else:
            system, prompt = self._prompts.render_messages(execution.profile.name, target, values)
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
        call_inference = (
            inference.model_copy(update={"max_output_tokens": 2048})
            if purpose == "interpretation"
            else inference
        )
        with llm_service.inference_context(call_inference):
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
            if on_token is None or not stream:
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
