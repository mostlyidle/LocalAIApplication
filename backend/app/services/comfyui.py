"""Small client for submitting explicit workflows to a local ComfyUI server."""

from __future__ import annotations

from typing import Any

import httpx


class ComfyUIClient:
    """Keep workflow execution local; this client only submits and returns its job id."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, workflow: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/prompt", json={"prompt": workflow})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                "ComfyUI is unavailable. Run it locally and configure COMFYUI_URL."
            ) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("ComfyUI returned an invalid response.") from exc
        if not isinstance(body, dict) or not isinstance(body.get("prompt_id"), str):
            raise RuntimeError("ComfyUI rejected the supplied workflow.")
        return body
