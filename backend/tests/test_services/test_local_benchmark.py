"""Checks for benchmark scoring and labeled-data validation."""

from __future__ import annotations

import argparse
import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.benchmark import RetrievalDataset, benchmark_embeddings, word_error_rate


def test_word_error_rate_accounts_for_edits() -> None:
    assert word_error_rate("Hello, WORLD!", "hello world") == 0
    assert word_error_rate("one two three", "one other three") == pytest.approx(1 / 3)
    assert word_error_rate("one two", "one two three") == 0.5


def test_dataset_rejects_missing_labels() -> None:
    with pytest.raises(ValidationError, match="existing document IDs"):
        RetrievalDataset.model_validate(
            {
                "documents": [{"id": "known", "text": "text"}],
                "questions": [{"query": "question", "relevant_ids": ["missing"]}],
            }
        )


async def test_retrieval_metrics_use_labeled_rankings(tmp_path) -> None:
    dataset = tmp_path / "corpus.json"
    dataset.write_text(
        json.dumps(
            {
                "documents": [{"id": str(i), "text": str(i)} for i in range(6)],
                "questions": [{"query": "last document", "relevant_ids": ["5"]}],
            }
        )
    )
    service = AsyncMock()
    service.get_identity.return_value = {"embedding_model": "test", "embedding_digest": "v1"}
    service.embed_texts.return_value = [[1, 0]] * 5 + [[0, 1]]
    service.embed_text.return_value = [0, 1]
    with patch("app.benchmark.EmbeddingService", return_value=service):
        result = await benchmark_embeddings(argparse.Namespace(dataset=dataset, models=["test"]))
    assert result[0]["recall_at_5"] == 1
    assert result[0]["mean_reciprocal_rank"] == 1
