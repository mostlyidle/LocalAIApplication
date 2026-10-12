import re
from collections.abc import Sequence
from types import SimpleNamespace

from qdrant_client import AsyncQdrantClient, models

from app.services.rag_store import RagStore


class FakeBm25Encoder:
    async def embed_documents(
        self, texts: Sequence[str], *, language: str, options: dict[str, object]
    ) -> list[models.SparseVector]:
        return [self._vector(text) for text in texts]

    async def embed_query(
        self, text: str, *, language: str, options: dict[str, object]
    ) -> models.SparseVector:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> models.SparseVector:
        terms = sorted(set(re.findall(r"[a-z0-9]+", text.casefold())))
        indices = sorted({sum(term.encode("utf-8")) for term in terms})
        return models.SparseVector(
            indices=indices,
            values=[1.0] * len(indices),
        )


def test_rrf_fuses_dense_and_bm25_rankings_and_preserves_citations() -> None:
    shared_payload = {
        "asset_id": "doc-1",
        "chunk_index": 2,
        "text": "Revenue increased in 2025.",
        "filename": "annual-report.pdf",
        "page_start": 4,
        "page_end": 5,
        "section": "Results",
    }
    rankings = [
        (
            "dense_original",
            1.0,
            [
                SimpleNamespace(id="chunk-1", score=0.9, payload=shared_payload),
                SimpleNamespace(
                    id="chunk-2",
                    score=0.8,
                    payload={"asset_id": "doc-2", "chunk_index": 1, "text": "Costs fell."},
                ),
            ],
        ),
        (
            "bm25_original",
            1.0,
            [
                SimpleNamespace(id="chunk-1", score=2.2, payload=shared_payload),
                SimpleNamespace(
                    id="chunk-3",
                    score=1.7,
                    payload={"asset_id": "doc-3", "chunk_index": 0, "text": "Profit rose."},
                ),
            ],
        ),
    ]

    passages, malformed_count = RagStore._fuse_rankings(
        rankings=rankings,
        rrf_k=60,
        result_limit=5,
    )

    assert malformed_count == 0
    assert [passage["point_id"] for passage in passages] == ["chunk-1", "chunk-2", "chunk-3"]
    assert passages[0]["score"] == 2 / 61
    assert passages[0]["provenance"] == {
        "filename": "annual-report.pdf",
        "page_start": 4,
        "page_end": 5,
        "section": "Results",
    }
    assert [source["ranking"] for source in passages[0]["sources"]] == [
        "dense_original",
        "bm25_original",
    ]


def test_rrf_omits_malformed_optional_candidates_without_losing_valid_results() -> None:
    passages, malformed_count = RagStore._fuse_rankings(
        rankings=[
            (
                "dense_original",
                1.0,
                [
                    SimpleNamespace(
                        id="bad", score=0.8, payload={"asset_id": "doc", "chunk_index": 0}
                    ),
                    SimpleNamespace(
                        id="good",
                        score=0.7,
                        payload={"asset_id": "doc", "chunk_index": 1, "text": "Valid text."},
                    ),
                ],
            )
        ],
        rrf_k=60,
        result_limit=5,
    )

    assert malformed_count == 1
    assert [passage["text"] for passage in passages] == ["Valid text."]


async def test_hybrid_search_runs_against_qdrants_local_engine(tmp_path) -> None:
    client = AsyncQdrantClient(path=str(tmp_path / "qdrant"))
    store = RagStore(
        "http://unused",
        client=client,
        bm25_encoder=FakeBm25Encoder(),
    )
    try:
        await store.upsert(
            collection="hybrid",
            chunks=["The QDR-42 filing deadline is Friday.", "Unrelated information."],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            asset_id="report",
            dense_model="deterministic-test",
            language="english",
        )

        result = await store.search(
            collection="hybrid",
            original_embedding=[1.0, 0.0],
            original_query="What is the QDR-42 filing deadline?",
            rewrite_embeddings=[],
            rewrite_queries=[],
            candidate_limit=10,
            result_limit=5,
            rrf_k=60,
            original_dense_weight=1,
            original_bm25_weight=1,
            rewrite_dense_total_weight=0,
            dense_model="deterministic-test",
            embedding_revision="default",
        )

        assert result.retrieval["mode"] == "hybrid_rrf"
        assert result.passages[0]["text"] == "The QDR-42 filing deadline is Friday."
        assert result.passages[0]["score_type"] == "rrf"
    finally:
        await store.close()
