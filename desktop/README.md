# Local AI desktop host

This is the Phase 3 Tauri 2 desktop host. Phase 3 supports a supervised macOS
source-checkout workflow; it is not a distributable desktop release. The host loads the
existing Next.js development frontend from `http://localhost:3000`. Bundling is disabled:
`frontend/.next` is not a Tauri production asset.

## Supported workflow: macOS source checkout

Run the workflow from the repository root with:

```sh
make dev-desktop
```

`make dev-desktop` runs `scripts/run-desktop-local.sh` in the foreground. The launcher owns
each backend, frontend, and Tauri process group and:

1. Refuses to adopt an existing listener on ports 8000 or 3000.
2. Runs `uv run alembic upgrade head` from `backend/`.
3. Starts the FastAPI backend on `127.0.0.1:8000` with one worker and waits for its
   HTTP health endpoint with `meeting_ready=true`.
4. Starts the Next.js development server on `127.0.0.1:3000` and waits for HTTP readiness.
5. Starts `cargo tauri dev` from `desktop/src-tauri`.

Readiness uses bounded curl timeouts (0.5 seconds to connect and 2 seconds total per request)
within a 20-second polling budget (with at most one in-flight request extending that bound).
HTTP 200 from `/api/v1/health` is not enough: the backend must
report `meeting_ready: true`. The backend and frontend are monitored while Tauri runs; an
unexpected death of any owned root stops the session. Pressing Ctrl-C or sending TERM exits
with the corresponding signal status (130/143) and terminates only the owned groups. Cleanup
sends TERM, waits five seconds, then escalates to KILL if necessary. Ollama and unrelated
listeners are never adopted or signalled. The launcher does not restart a crashed child;
inspect the diagnostic output and rerun `make dev-desktop` after correcting the problem.

### One-time setup

Install the dependencies before the first run. The Tauri CLI is installed separately from
the Rust toolchain:

```sh
cd backend && uv sync
cd ../frontend && pnpm install
cargo install tauri-cli --version '^2'
```

The backend is started with `backend/` as its working directory, so desktop-specific
settings should be in `backend/.env` or exported in the shell. Copy the repository example
and replace the ASR placeholder before starting:

```sh
cp .env.example backend/.env
mkdir -p backend/data/uploads backend/data/chroma
${EDITOR:-vi} backend/.env
```

Relative backend paths such as `./data/app.db`, `./data/uploads`, and `./data/chroma` resolve
under `backend/` for this launcher.

The frontend defaults to the local backend and does not require an additional env file for
this workflow. If `frontend/.env.local` is present, use `NEXT_PUBLIC_API_URL=http://localhost:8000`
and `NEXT_PUBLIC_WS_URL=ws://localhost:8000`.

## macOS build requirements

- Apple Silicon Mac running macOS **13.0 or later**.
- The full Xcode application, with its license/first-launch setup complete. Xcode Command
  Line Tools alone are not sufficient: the native bridge links AVFAudio, AVFoundation,
  CoreAudio, CoreGraphics, CoreMedia, and ScreenCaptureKit from the macOS SDK.
- Rust stable, `uv`, Node.js, and pnpm.
- Tauri 2 CLI (`cargo install tauri-cli --version '^2'`).

Verify that the selected developer directory is the full Xcode installation, then run the
native checks:

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -version
cd desktop/src-tauri
cargo fmt --check
cargo check
cargo tauri info
```

The Tauri configuration sets `minimumSystemVersion` to `13.0`. The native implementation
uses ScreenCaptureKit for system audio and AVAudioEngine for the microphone. The bundle
contains the macOS usage descriptions and audio-input entitlement required by the host.

## Offline ASR provisioning

Meeting transcription uses `faster-whisper` with CPU `int8`, English, and built-in VAD. The
model must be provisioned before a meeting and before an offline run:

- Provide an existing local CTranslate2 model directory named exactly `small.en`.
- Set `ASR_MODEL_DIR` to that directory's **absolute** path in `backend/.env` (for example,
  `/Users/me/Library/Application Support/LocalAIApplication/models/small.en`).
- Keep `ASR_MODEL_NAME=small.en`.
- Provision/copy the complete model artifact outside the meeting runtime. Do not point at a
  relative path, a model name, or a parent directory.

The runtime validates that the directory exists, is absolute, and has the `small.en`
basename. Readiness loads it with `local_files_only=True`; no ASR download is attempted
during startup, preflight, or a meeting. If the directory is missing, incomplete, or the
`faster-whisper` dependency is unavailable, readiness fails and the meeting must not start.
Do not use `make setup` as an offline provisioning step: that target pulls Ollama models.

## Migrations, health, and readiness diagnostics

The supervised launcher applies migrations before starting the backend. To diagnose a
migration failure independently:

```sh
cd backend
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
```

After the backend is running, inspect the complete health response:

```sh
curl -sS http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
```

`GET /api/v1/health` returns HTTP 200 even when a dependency is unhealthy. Check these
fields rather than HTTP status alone:

- `meeting_ready` must be `true` for a meeting. The required services are `local_asr` and
  `app_database`.
- `services[].name == "local_asr"` reports the bounded local `small.en` load check (normally
  limited to five seconds) and its actionable error message.
- `services[].name == "ollama"` and `"qdrant"` are optional for meeting capture and answer
  suggestions; their failure is reported as degradation.

The backend initializes its application database and reconciles meetings left `active` by a
previous backend process. Such meetings are marked `failed`, their persisted transcript is
preserved, and their missing audio cannot be recovered. Start a new meeting to continue.

For optional Ollama diagnostics, use the local-only API:

```sh
curl -sS http://127.0.0.1:11434/api/tags
```

## Permissions and audio disclosure

On macOS, grant both **Screen Recording** and **Microphone** to the debug/signed app in
**System Settings → Privacy & Security**. The meeting preflight exposes permission state and
the UI provides request, settings, and recheck actions. If a request is denied:

1. Open the relevant Privacy & Security pane from the app (or use System Settings).
2. Enable access for the Local AI Application debug/signed app.
3. Recheck permissions in the app before retrying capture; do not assume the earlier request
   changed the state.

Permission responses distinguish `notDetermined`, `granted`, `denied`, and `unknown` (macOS
Screen Recording can remain `unknown` until the OS grant is visible). On Windows, microphone
privacy is reported as `unknown` and the settings action opens `ms-settings:privacy-microphone`;
the macOS request flow does not apply there.

Screen Recording is used for system audio. The system source is a **display-wide system mix
from the render endpoint**, not a Teams-only or per-process stream, and it may include music,
alerts, notifications, or other non-meeting sound. This source-checkout workflow does not
provide per-process audio selection or claim Teams isolation. The microphone is captured as a
separate source. Tell meeting participants and other affected users what will be captured and
obtain any consent required for the meeting; the native capability does not make that disclosure
for you.

## Capture, transcript, and deletion behavior

Raw PCM remains in bounded native memory and the bounded backend processor queue only. It is
not sent through Tauri IPC events, serialized into frontend events, written to SQL, or written
to logs. The native ring buffer is limited to 10 seconds at 48 kHz (with format-dependent
frame capacity); capture reports dropped-frame counters when it overflows.

Only final local-ASR transcript segments, source labels (`microphone` or `system`), meeting
metadata, and detected questions are persisted. Answer suggestions are streamed locally and
are not a separate persisted record. To remove a meeting and its persisted transcript/questions,
call:

```sh
MEETING_ID="replace-with-meeting-id"
curl -X DELETE "http://127.0.0.1:8000/api/v1/meetings/${MEETING_ID}"
```

Deletion purges the meeting processor state before deleting the meeting rows. It does not
delete unrelated uploaded documents or RAG collections. A normal stop flushes the remaining
bounded windows; a disconnect or process failure purges in-memory audio without reconstructing
missing audio.

## Operational limits and recovery

- One active audio WebSocket/session is allowed per meeting.
- The desktop sends at most one unacknowledged chunk per source. Chunks are 960 frames;
  transport payloads are limited to 192,000 bytes and the protocol is `meeting-audio.v1`.
- The backend processor queue defaults to 128 items and processes rolling 2,000 ms windows.
  Queue saturation is surfaced as processor backpressure; capture drops are surfaced
  separately as discarded audio.
- A local WebSocket connection tries localhost addresses with bounded connection/handshake
  timeouts and at most five reconnect attempts. A connection stable for at least one second
  resets the retry count. Stop drains backend events for up to two seconds; a missing stopped
  status is reported as a transport error.
- Transport and capture shutdown are intended to be idempotent. If the desktop or backend
  exits, rerun `make dev-desktop`; startup reconciliation marks stale active meetings failed.
  Persisted transcript text remains available until the meeting is explicitly deleted.

## Optional Ollama and RAG

Ollama is not required for native capture or local transcription. It provides private answer
suggestions for detected **system-source** questions when available. Qdrant/RAG is disabled
by default for meetings; set `MEETING_ENABLE_RAG=true` only when the local Qdrant store and
embedding setup are available. If Ollama or RAG is unavailable, the backend emits a visible
`degraded` event and transcription continues. No cloud service or API key is required.

## Windows and packaging gates

Windows support is target-gated and is not validated by a macOS build. Windows requires a
Windows 10 2004-or-later host/CI runner and must be smoke-tested there for WASAPI loopback,
CPAL microphone capture, WAVEFORMATEXTENSIBLE devices, silent WASAPI packets, and microphone
privacy denial. Windows system audio is likewise a render-endpoint system mix, not
per-process Teams audio.

Packaging is intentionally disabled (`bundle.active=false`). Before any installer or signed
release, the project still needs a production frontend asset strategy, a managed/supervised
FastAPI runtime including the canonical meeting WebSocket, and an explicit desktop-to-backend
endpoint and lifecycle policy. Windows hardware smoke, signing, installers, and a packaged
backend runtime are release gates, not claims of this source-checkout workflow.

## Native control plane and checks

The native control plane exposes `get_capabilities`, `get_permissions`, `list_audio_devices`,
`request_permissions`, `open_permission_settings`, `start_capture`, `stop_capture`, and
`get_capture_status`. Only bounded meter and status events (`capture://meter` and
`capture://status`) are sent to the frontend. The PCM drain/transport path is intentionally
not a frontend IPC command.

The canonical byte fixture is `../meeting-contract/golden_envelope.hex`; Rust transport tests
consume that shared fixture so protocol changes cannot silently diverge.

```sh
cd desktop/src-tauri
cargo fmt --check
cargo check
cargo test
cargo build
cargo tauri info
```

The deterministic launcher checks can be run without starting the application:

```sh
# From the repository root
make test-desktop-launcher
```

This verifies that `meeting_ready=false` is rejected and that an owned process group is
cleaned up without using broad process or port-based termination.

The macOS implementation requires the full Xcode SDK and the
ScreenCaptureKit/AVFAudio-related frameworks. Windows validation must run on Windows because
the WASAPI and CPAL modules are target-gated and cannot be exercised by a macOS build.
