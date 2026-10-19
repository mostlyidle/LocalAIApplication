"""Download the pinned GLiNER PII model into the local Hugging Face cache."""

from __future__ import annotations

from huggingface_hub import snapshot_download

from app.services.redaction_detector import MODEL_ID, MODEL_REVISION
from app.config import settings


def main() -> None:
    """Cache the exact model revision used by the redaction detector."""
    cache_dir = settings.redaction_model_cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache_dir,
    )
    print(f"Downloaded {MODEL_ID}@{MODEL_REVISION} into {cache_dir}")


if __name__ == "__main__":
    main()
