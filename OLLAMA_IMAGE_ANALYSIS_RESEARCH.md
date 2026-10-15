# Image analysis and Ollama payload research

Checked on 2026-10-14 against the local app and Ollama service.

## Image payload format

The app's current image path is correct. It reads the uploaded file into bytes,
base64-encodes those bytes, then places them in a `data:image/...;base64,...`
content block for LangChain's `ChatOllama` adapter
([task runner](backend/app/services/task_runner.py#L161),
[message conversion](backend/app/services/task_runner.py#L377)). Ollama's
official vision docs say its SDKs accept paths, URLs, or raw bytes, while its
JSON REST API expects base64 image data in the `images` field
([Ollama vision API](https://github.com/ollama/ollama/blob/main/docs/capabilities/vision.mdx#L200-L219)).

The app pins `langchain-ollama` 1.0.1. That adapter accepts inline base64 image
content and converts it to Ollama's `images` field; raw Python bytes are not the
format used by this `image_url` content block
([pinned adapter source](https://github.com/langchain-ai/langchain/blob/langchain-ollama%3D%3D1.0.1/libs/partners/ollama/langchain_ollama/chat_models.py#L3553-L3597)).
So reading the upload as bytes is necessary, and base64 is the correct wire
encoding for this app's JSON-based adapter path.

## Reload and retry result

- `ollama pull llama3.2-vision:11b` completed successfully. It refreshed the
  existing tag; it did not add another model.
- A direct `ChatOllama` request with the app's image content format still failed
  with `unknown model architecture: 'mllama'`.
- A text-only control against the same model failed with the identical loader
  error, confirming that image encoding is not what triggers this failure.
- The live chat retry with the same local image also failed. The app showed its
  generic agent error.
- The local Ollama service reports version `0.40.3`. The current Ollama server
  source has a compatibility check for legacy `mllama` vision artifacts and
  recommends re-pulling `llama3.2-vision`; that re-pull has now been tried here
  without resolving the error
  ([Ollama server compatibility check](https://github.com/ollama/ollama/blob/main/server/routes.go#L2631-L2639)).
- This exact `mllama` failure is also reported in Ollama's issue tracker after a
  fresh model pull. The linked Ollama release notes list `llama3.2-vision` as
  unsupported in the llama.cpp-based runtime, and an Ollama maintainer says the
  architecture had not been implemented there
  ([issue and maintainer comments](https://github.com/ollama/ollama/issues/16490),
  [release notes](https://github.com/ollama/ollama/releases/tag/v0.30.0)).
  This supports a runtime/model compatibility regression as the likely cause,
  though the issue thread does not establish the right fix for local version
  `0.40.3`.

The evidence points to an Ollama model-runner/artifact compatibility problem,
not a missing bytes conversion in the app. The app's UI currently hides the
specific Ollama error, so the backend/runner log is the useful next diagnostic
if this still fails after a runner restart or a future Ollama fix.

Ollama's Llama 3.2 Vision page documents the supported model and image request
shape ([official model guide](https://ollama.com/blog/llama3.2-vision)).
