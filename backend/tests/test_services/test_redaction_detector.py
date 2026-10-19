"""Tests for local redaction candidate selection and persisted geometry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import app.services.redaction_detector as detector
import app.services.redaction_job_worker as worker
from app.services.redaction_documents import ExtractedPage, WordRegion

if TYPE_CHECKING:
    from pathlib import Path


class FakeModel:
    def to(self, _device: str) -> FakeModel:
        return self

    def eval(self) -> None:
        return None

    def predict_entities(
        self, text: str, labels: list[str], *, threshold: float
    ) -> list[dict[str, object]]:
        assert threshold == 0.3
        result = []
        for label in labels:
            value = "Alex" if label == "person" else "alex@example.com"
            start = text.find(value)
            if start >= 0:
                result.append(
                    {
                        "start": start,
                        "end": start + len(value),
                        "label": label,
                        "score": 0.8,
                    }
                )
        return result


@pytest.mark.asyncio
async def test_only_requested_labels_are_detected_and_employee_label_is_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(detector, "_get_model", lambda _cache: FakeModel())
    page = ExtractedPage(
        number=0,
        width=300,
        height=100,
        text="Employee Name: Alex Example\nEmail: alex@example.com",
        words=(
            WordRegion(15, 27, (100, 10, 180, 30), (0, 0)),
            WordRegion(35, 52, (60, 40, 200, 60), (0, 1)),
        ),
    )

    findings = await detector.detect_candidates(
        page,
        ["person name", "email address"],
        cache_dir=tmp_path,
    )

    assert {(item["category"], item["text"]) for item in findings} == {
        ("person name", "Alex Example"),
        ("email address", "alex@example.com"),
    }
    assert len(findings) == 2


def test_page_data_round_trips_source_geometry() -> None:
    page = ExtractedPage(
        number=1,
        width=612,
        height=792,
        text="Confidential",
        words=(WordRegion(0, 12, (20, 30, 110, 50), (1, 0), "ocr", 0.2),),
    )

    assert detector.page_from_data(detector.page_data(page)) == page


@pytest.mark.asyncio
async def test_contextual_selection_is_limited_to_candidate_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_payload: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"message": {"content": '{"selected_ids":[0],"ambiguous":false}'}}

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, *, json: dict[str, object]) -> FakeResponse:
            request_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeClient)
    candidates = [
        {"text": "Alex Example", "start": 10, "end": 22, "category": "person", "selected": True},
        {"text": "Dana Example", "start": 40, "end": 52, "category": "person", "selected": True},
    ]

    await worker.select_contextual_candidates(
        "Employee: Alex Example\nManager: Dana Example",
        candidates,
        "Redact the employee but not the manager.",
    )

    assert [candidate["selected"] for candidate in candidates] == [True, False]
    system_prompt = request_payload["messages"][0]["content"]  # type: ignore[index]
    assert "untrusted data" in system_prompt
