"""Docling adapter and citation tests with deterministic conversion output."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.middleware.error_handler import DocumentParseError
from app.services.document_parser import DocumentParserService, ParsedDocument


def test_chunk_pages_keep_provenance() -> None:
    parser = DocumentParserService()
    parsed = ParsedDocument(
        text="all pages",
        blocks=[
            {"text": "Revenue grew.", "page": 1, "section": "Results"},
            {"text": "Costs fell.", "page": 2, "section": "Costs"},
        ],
    )
    chunks = parser.chunk_document(parsed, {"source": "report.pdf", "document_id": "doc"})
    assert [c["metadata"]["page"] for c in chunks] == [1, 2]
    assert [c["metadata"]["chunk_index"] for c in chunks] == [0, 1]
    assert chunks[1]["metadata"]["section"] == "Costs"
    assert all(c["metadata"]["source"] == "report.pdf" for c in chunks)


async def test_docling_requires_local_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.document_parser.settings.docling_artifacts_path", None)
    with pytest.raises(DocumentParseError, match="provisioned"):
        await DocumentParserService()._parse_pdf_docling(Path("scan.pdf"))


@pytest.fixture
def conversion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Supply external Docling types and converter without importing model runtimes."""
    monkeypatch.setattr(
        "app.services.document_parser.settings.docling_artifacts_path", str(tmp_path)
    )
    monkeypatch.setattr("app.services.document_parser.settings.pdf_parser", "docling")

    class Table:
        label = "table"
        prov = [types.SimpleNamespace(page_no=2)]

        def export_to_dataframe(self, **kwargs: object) -> object:
            return types.SimpleNamespace(
                columns=["Code", "Value"],
                itertuples=lambda **options: iter([("ABC", 42)]),
            )

        def export_to_markdown(self, **kwargs: object) -> str:
            return "| Code | Value |\n| ABC | 42 |"

    heading = types.SimpleNamespace(
        text="Results", label="heading", prov=[types.SimpleNamespace(page_no=1)]
    )
    paragraph = types.SimpleNamespace(
        text="Scanned text", label="paragraph", prov=[types.SimpleNamespace(page_no=1)]
    )
    document = types.SimpleNamespace(
        pages={1: None, 2: None},
        iterate_items=lambda: iter([(heading, 0), (paragraph, 0), (Table(), 0)]),
    )
    converter = MagicMock()
    converter.convert.return_value = types.SimpleNamespace(status="success", document=document)
    modules = {
        "docling.datamodel.base_models": {
            "ConversionStatus": types.SimpleNamespace(SUCCESS="success"),
            "InputFormat": types.SimpleNamespace(PDF="pdf"),
        },
        "docling.datamodel.pipeline_options": {
            "EasyOcrOptions": MagicMock(side_effect=lambda **kw: types.SimpleNamespace(**kw)),
            "PdfPipelineOptions": MagicMock(side_effect=lambda **kw: types.SimpleNamespace(**kw)),
        },
        "docling.document_converter": {
            "DocumentConverter": MagicMock(return_value=converter),
            "PdfFormatOption": MagicMock(side_effect=lambda **kw: types.SimpleNamespace(**kw)),
        },
        "docling_core.types.doc": {
            "TableItem": Table,
            "DocItemLabel": types.SimpleNamespace(SECTION_HEADER="heading", TITLE="title"),
        },
    }
    for name, values in modules.items():
        module = types.ModuleType(name)
        for key, value in values.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    return converter


async def test_convert_maps_text_tables_and_citations(conversion: MagicMock) -> None:
    parser = DocumentParserService()
    parsed = await parser._parse_pdf(Path("report.pdf"))
    assert "Scanned text" in parsed.text
    assert parsed.page_count == 2
    assert parsed.tables == [{"page": 2, "headers": ["Code", "Value"], "rows": [["ABC", "42"]]}]
    chunks = parser.chunk_document(parsed, {"source": "report.pdf"})
    assert chunks[-1]["metadata"]["page"] == 2
    assert chunks[-1]["metadata"]["section"] == "Results"
    options = sys.modules["docling.datamodel.pipeline_options"].PdfPipelineOptions.call_args.kwargs
    assert options["enable_remote_services"] is False
    assert options["ocr_options"].download_enabled is False
    assert conversion.convert.call_args.kwargs["max_num_pages"] == 1_000


async def test_partial_conversion_is_not_silently_ingested(conversion: MagicMock) -> None:
    conversion.convert.return_value.status = "partial_success"
    with pytest.raises(DocumentParseError, match="completely"):
        await DocumentParserService()._parse_pdf(Path("report.pdf"))
