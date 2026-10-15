"""Public behavior tests for the local Laya decision client."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.laya_rag import LayaCalibration, LayaDecision, LayaRagService


@pytest.mark.asyncio
async def test_check_rewrite_parses_a_valid_decision_and_posts_to_systemone() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "laya:latest",
                "answers": {
                    "rewrite": {
                        "type": "choice",
                        "choice": "skip",
                        "probabilities": {"skip": 0.92, "run": 0.04, "uncertain": 0.04},
                        "confidence": 0.85,
                    }
                },
            },
        )

    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond),
    )
    try:
        decision = await service.check_rewrite("What is the warranty duration for QDR-42?")
    finally:
        await service.close()

    assert decision.check == "rewrite"
    assert decision.choice == "skip"
    assert decision.probability == pytest.approx(0.92)
    assert decision.reason == "evaluated"
    assert decision.schema_version == "rewrite-v1"
    assert str(requests[0].url) == "http://ollama.test/v1/systemone"
    payload = requests[0].read().decode()
    assert '"type":"choice"' in payload
    assert "QDR-42" in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        {"type": "choice", "choice": "skip", "probabilities": {"skip": 1.0}},
        {
            "type": "choice",
            "choice": "other",
            "probabilities": {"skip": 0.5, "run": 0.3, "uncertain": 0.2},
        },
        {
            "type": "choice",
            "choice": "skip",
            "probabilities": {"skip": 0.7, "run": 0.2, "uncertain": 0.2},
        },
        {
            "type": "choice",
            "choice": "skip",
            "probabilities": {"skip": True, "run": 0, "uncertain": 0},
        },
    ],
)
async def test_malformed_decision_abstains(answer: dict[str, object]) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answers": {"rewrite": answer}},
        )

    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond),
    )
    try:
        decision = await service.check_rewrite("A specific question")
    finally:
        await service.close()

    assert decision.choice is None
    assert decision.probability is None
    assert decision.reason == "invalid_response"


@pytest.mark.asyncio
async def test_timeout_returns_an_abstention() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request timed out", request=request)

    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond), timeout_ms=10,
    )
    try:
        decision = await service.check_rewrite("A specific question")
    finally:
        await service.close()

    assert decision.choice is None
    assert decision.reason == "timeout"


@pytest.mark.asyncio
async def test_response_from_another_model_abstains() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "different-model:latest",
                "answers": {
                    "rewrite": {
                        "type": "choice",
                        "choice": "skip",
                        "probabilities": {
                            "skip": 0.92,
                            "run": 0.04,
                            "uncertain": 0.04,
                        },
                    }
                },
            },
        )

    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond),
    )
    try:
        decision = await service.check_rewrite("A specific question")
    finally:
        await service.close()

    assert decision.choice is None
    assert decision.reason == "invalid_response"


@pytest.mark.asyncio
async def test_start_checks_inventory_and_warms_laya_in_background() -> None:
    warm_request = asyncio.Event()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "laya:latest", "digest": "installed-digest"}
                    ]
                },
            )
        warm_request.set()
        return httpx.Response(
            200,
            json={
                "model": "laya:latest",
                "answers": {
                    "rewrite": {
                        "type": "choice",
                        "choice": "skip",
                        "probabilities": {
                            "skip": 0.92,
                            "run": 0.04,
                            "uncertain": 0.04,
                        },
                    }
                },
            },
        )

    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond),
        calibration=LayaCalibration(
            model="laya:latest",
            model_digest="installed-digest",
        ),
    )
    try:
        await service.start(enabled=True)
        assert not service.is_ready
        await asyncio.wait_for(warm_request.wait(), timeout=0.5)
        assert service.is_ready
        assert service.model_digest == "installed-digest"
        assert service.calibration_digest_matches
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_calibrated_rewrite_gate_requires_approved_scope_and_threshold() -> None:
    warmed = asyncio.Event()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "laya:latest", "digest": "approved-digest"}]},
            )
        warmed.set()
        return httpx.Response(
            200,
            json={
                "model": "laya:latest",
                "answers": {
                    "rewrite": {
                        "type": "choice",
                        "choice": "skip",
                        "probabilities": {"skip": 0.92, "run": 0.05, "uncertain": 0.03},
                    }
                },
            },
        )

    service = LayaRagService(
        base_url="http://ollama.test",
        model="laya:latest",
        transport=httpx.MockTransport(respond),
        calibration=LayaCalibration(
            model="laya:latest",
            model_digest="approved-digest",
            tokenizer_server_parity_verified=True,
            checks={
                "rewrite": {
                    "schema_version": "rewrite-v1",
                    "thresholds": {"skip": 0.9},
                    "approved_profiles": ["rag_v2"],
                    "approved_prompt_digests": ["approved-prompt"],
                    "max_request_bytes": 20_000,
                }
            },
        ),
    )
    try:
        await service.start(enabled=True)
        await asyncio.wait_for(warmed.wait(), timeout=0.5)
        decision = await service.check_rewrite("A specific question")

        allowed, reason = service.can_apply(
            "rewrite",
            profile="rag_v2",
            prompt_digest="approved-prompt",
            decision=decision,
        )
        wrong_profile, profile_reason = service.can_apply(
            "rewrite",
            profile="rag",
            prompt_digest="approved-prompt",
            decision=decision,
        )
        wrong_prompt, prompt_reason = service.can_apply(
            "rewrite",
            profile="rag_v2",
            prompt_digest="unreviewed-prompt",
            decision=decision,
        )
        incomplete, coverage_reason = service.can_apply(
            "rewrite",
            profile="rag_v2",
            prompt_digest="approved-prompt",
            decision=decision,
            input_covered=False,
        )
    finally:
        await service.close()

    assert allowed is True and reason == "threshold_met"
    assert wrong_profile is False and profile_reason == "profile_unverified"
    assert wrong_prompt is False and prompt_reason == "prompt_unverified"
    assert incomplete is False and coverage_reason == "budget_exceeded"


@pytest.mark.asyncio
async def test_check_evidence_sends_the_complete_supplied_passages() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "model": "laya:latest",
                "answers": {
                    "evidence": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {
                            "supported": 0.9,
                            "unsupported": 0.05,
                            "uncertain": 0.05,
                        },
                    }
                },
            },
        )

    passages = ["Opening passage.", "A later passage contains the complete answer."]
    service = LayaRagService(
        base_url="http://ollama.test", model="laya:latest",
        transport=httpx.MockTransport(respond),
    )
    try:
        decision = await service.check_evidence("What is the answer?", passages)
    finally:
        await service.close()

    assert decision.check == "evidence"
    assert decision.choice == "supported"
    assert captured[0]["state"] == {
        "question": "What is the answer?",
        "evidence": passages,
    }


@pytest.mark.asyncio
async def test_oversized_evidence_abstains_without_sending_a_truncated_request() -> None:
    requests: list[httpx.Request] = []
    service = LayaRagService(
        base_url="http://ollama.test",
        model="laya:latest",
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(500)
        ),
    )
    try:
        decision = await service.check_evidence("Question", ["x" * (65 * 1024)])
    finally:
        await service.close()

    assert decision.choice is None
    assert decision.reason == "budget_exceeded"
    assert decision.input_bytes > 64 * 1024
    assert requests == []


@pytest.mark.asyncio
async def test_checked_in_calibration_cannot_enforce_before_tokenizer_and_threshold_review() -> None:
    service = LayaRagService(base_url="http://ollama.test", model="laya:latest")
    decision = LayaDecision(
        check="rewrite",
        choice="skip",
        probability=0.99,
        probabilities={"skip": 0.99, "run": 0.005, "uncertain": 0.005},
        input_bytes=500,
        elapsed_ms=1,
        schema_version="rewrite-v1",
        reason="evaluated",
    )

    try:
        allowed, reason = service.can_apply(
            "rewrite",
            profile="rag_v2",
            prompt_digest="unapproved",
            decision=decision,
        )
    finally:
        await service.close()

    assert allowed is False
    assert reason == "not_calibrated"
