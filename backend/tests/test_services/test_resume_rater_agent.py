"""Evidence and deterministic scoring checks for resume assessments."""

from __future__ import annotations

import pytest

from app.models.resume_rater_schemas import (
    ResumeRaterModelReport,
    ResumeRaterReport,
    ResumeRubric,
)
from app.services.resume_rater_agent import (
    _public_report,
    prepare_resume_evidence,
    validate_report_evidence,
    weighted_score,
)


def _rubric() -> ResumeRubric:
    return ResumeRubric(
        criteria=[
            {
                "id": "experience",
                "label": "Experience",
                "description": "Relevant experience",
                "weight": 40,
            },
            {"id": "skills", "label": "Skills", "description": "Required skills", "weight": 30},
            {
                "id": "leadership",
                "label": "Leadership",
                "description": "Team leadership",
                "weight": 20,
                "must_have": True,
            },
            {
                "id": "communication",
                "label": "Communication",
                "description": "Clear communication",
                "weight": 10,
            },
        ]
    )


def _report() -> ResumeRaterReport:
    return ResumeRaterReport(
        summary="Evidence is strongest in experience and skills.",
        criterion_scores=[
            {
                "criterion_id": "experience",
                "level": "fully_meets",
                "explanation": "Long relevant tenure.",
                "evidence_quotes": ["Built reliable services for eight years."],
            },
            {
                "criterion_id": "skills",
                "level": "substantial",
                "explanation": "Most listed skills are relevant.",
                "evidence_quotes": ["Python and SQL delivery."],
            },
            {
                "criterion_id": "leadership",
                "level": "partial",
                "explanation": "Mentoring is mentioned.",
                "evidence_quotes": ["Mentored two engineers."],
            },
            {
                "criterion_id": "communication",
                "level": "not_demonstrated",
                "explanation": "No direct example found.",
                "evidence_quotes": [],
            },
        ],
        gaps=[],
        strengths=[],
    )


def test_weighted_score_uses_the_approved_rubric() -> None:
    assert weighted_score(_report(), _rubric()) == 73


def test_report_quotes_must_be_present_verbatim() -> None:
    report = _report()
    report.criterion_scores[0].evidence_quotes = ["Built excellent services."]
    with pytest.raises(ValueError, match="does not appear"):
        validate_report_evidence(report, "Built reliable services for eight years.", _rubric())


def test_each_rubric_criterion_must_be_scored_once() -> None:
    report = _report()
    report.criterion_scores.pop()
    with pytest.raises(ValueError, match="each approved criterion"):
        validate_report_evidence(
            report,
            "Built reliable services for eight years. Python and SQL delivery. Mentored two engineers.",
            _rubric(),
        )


def test_strengths_and_gaps_require_exact_resume_evidence() -> None:
    payload = _report().model_dump()
    payload["strengths"] = [
        {"criterion_id": "experience", "text": "Long tenure.", "evidence_quotes": []}
    ]
    with pytest.raises(ValueError, match="at least 1 item"):
        ResumeRaterReport.model_validate(payload)

    report = _report()
    report.gaps = [
        {
            "criterion_id": "leadership",
            "text": "The resume mentions mentoring.",
            "evidence_quotes": ["This quote is absent."],
        }
    ]
    with pytest.raises(ValueError, match="does not appear"):
        validate_report_evidence(report, "Mentored two engineers.", _rubric())


def test_model_suggestions_cannot_add_unsupported_facts() -> None:
    payload = _report().model_dump()
    payload["resume_suggestions"] = [
        {
            "focus": "clarify_scope",
            "source_quote": "Built reliable services for eight years.",
            "text": "Highlight your eight direct reports.",
        }
    ]
    model_report = ResumeRaterModelReport.model_validate(payload)
    report = _public_report(model_report)

    assert report.resume_suggestions[0].text == "Clarify your specific role and scope in this work."
    assert "direct reports" not in report.resume_suggestions[0].text
    validate_report_evidence(
        model_report,
        "Built reliable services for eight years. Python and SQL delivery. Mentored two engineers.",
        _rubric(),
    )


def test_personal_contact_fields_are_removed_before_model_assessment() -> None:
    evidence = prepare_resume_evidence(
        "Alex Doe\nalex@example.com\nSenior software engineer\nAge: 41\n"
        "Built reliable services for eight years."
    )
    assert "Alex Doe" not in evidence
    assert "alex@example.com" not in evidence
    assert "Age: 41" not in evidence
    assert "Built reliable services for eight years." in evidence


def test_model_report_rejects_an_invalid_rubric_weight_total() -> None:
    payload = _report().model_dump()
    payload["criterion_scores"] = payload["criterion_scores"][:2]
    with pytest.raises(ValueError):
        ResumeRaterModelReport.model_validate(payload)
