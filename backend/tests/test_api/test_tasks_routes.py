from pathlib import Path
from unittest.mock import AsyncMock

from httpx import AsyncClient

from app.models.db_models import Document
from app.models.profile_schemas import AgentResult


async def test_task_route_resolves_uploaded_asset_id(
    client: AsyncClient,
    db_session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"image bytes")
    document = Document(
        id="uploaded-image",
        filename="image.png",
        format="png",
        size_bytes=11,
        storage_path=str(path),
    )
    db_session.add(document)
    await db_session.commit()
    runner = AsyncMock()
    runner.run.return_value = AgentResult(agent="image_analysis", answer="A test image.")
    client._transport.app.state.task_runner = runner

    response = await client.post(
        "/api/v1/tasks",
        json={"prompt": "Describe it", "target": "image_analysis", "asset_id": document.id},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "A test image."
    call = runner.run.await_args
    assert call.kwargs["document"].id == document.id
    assert call.kwargs["request_id"]


async def test_task_route_does_not_accept_a_filesystem_path_as_an_asset_id(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"prompt": "Describe it", "target": "image_analysis", "asset_id": "/tmp/image.png"},
    )

    assert response.status_code == 404
