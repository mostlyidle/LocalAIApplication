# Document Redaction Agent — Implementation Plan

Date: 2026-10-19

Status: Core redaction workflow and contextual clarification interaction are implemented on
`main`. Remaining work is release hardening and representative-document calibration; this is
not a claim that the detector finds every sensitive value.

## Agreed first-version behavior

- Process one PDF, scanned PDF, PNG, or JPEG per job, entirely locally after model setup.
- Target printed English text and validated Canadian/US identifier formats.
- Offer categories for names, employee numbers, emails, addresses, salary, government
  identifiers, and driver's licence numbers, plus custom instructions.
- Support contextual requests such as “redact the employee's name but retain the
  manager's name”; request clarification when the instruction or role is ambiguous.
- Default to all matching occurrences and redact values while preserving field labels.
- Favor recall, displaying uncertain candidates for mandatory human review.
- Provide page-by-page preview, category filtering, editable boxes, progress, and cancellation.
- Support manual boxes for handwriting, signatures, faces, and QR/barcodes. Automatic
  recognition of those visual elements is outside the first version.
- Export a fresh image-based PDF. Its text will not be selectable/searchable; forms,
  links, digital signatures, and interactive document behavior will not be preserved.
- Retain the private original separately. A redacted copy does not sanitize the original
  or existing RAG content derived from it.
- Resolve failed pages through retry, whole-page redaction, or explicit manual inspection
  and approval. An unrenderable page cannot be manually approved or exported unresolved.

## Proposed workflow

1. Select **Document Redaction**, attach/select an owned document, choose categories,
   and enter optional instructions.
2. Display the interpreted policy, including exclusions. Resolve ambiguous instructions
   before detection; never silently ignore an unsupported request.
3. Create a saved job and render/process every page. Show stage/page progress and failures.
4. Open the review workspace with page images, proposed redaction boxes, categories,
   uncertain detections, and pages requiring manual attention.
5. Let the user accept/remove/resize boxes or draw new ones. Failed extraction requires
   a distinct manual-review acknowledgement, not merely a global export confirmation.
6. Approve a specific review revision and generate the redacted PDF from that snapshot.
7. Validate the saved artifact, then allow download. Editing the policy or boxes invalidates
   approval and any previous export for that revision.

## Model responsibilities

**GLiNER PII:** Primary candidate detector. Evaluate `nvidia/gliner-PII`, a 570M-parameter,
non-generative English span detector. It returns text offsets and scores, rather than
editing documents or following arbitrary instructions. Its documented platform list does
not establish Apple Silicon support; compatibility must be measured locally. The model
uses the NVIDIA Open Model License. [Official model card](https://huggingface.co/nvidia/gliner-PII)

**Identifier rules:** Supplement detection with contextual patterns and available checksums
for structured identifiers. Cover exact requested values and validated employee-ID formats.
Avoid treating every number, currency amount, or date as sensitive by default. Publish the
specific Canadian/US formats evaluated; country scope is not a claim of coverage for every
province, state, or issuing authority.

**Local Ollama model:** Use the existing Qwen 2.5 7B profile as the initial contextual
baseline. Translate instructions into a validated policy and resolve contextual selections
using document evidence. It may propose candidate spans beyond GLiNER's suggestions,
but every candidate must map to actual source text. It must not invent text or coordinates.
Evaluate a smaller instruction model only if the baseline's resource use warrants it.

For role-specific instructions, do not silently propagate a person's name to every occurrence:
identical names can identify different people. Preserve unresolved role matches as uncertain
and ask for clarification/review rather than confidently excluding them.

Treat document text as untrusted data, not instructions. Keep document content out of
account memory, automatic RAG ingestion, and general chat history by default. Persist only
the private job data needed to run/review this workflow; logs contain IDs, counts, and stages.

## Extraction and coordinate mapping

Build a redaction-specific extraction path; do not reuse truncated analysis context or RAG chunks.

- Render canonical page images and preserve page dimensions, rotation, crop, and image
  orientation transforms. Review and export use the same coordinate system and appearance.
- Extract native PDF text with word/character geometry. OCR rendered content where needed,
  including image regions on mixed text/image pages; a native text layer is not proof that
  all visible text was extracted. Reconcile duplicate native/OCR results.
- Keep an offset-to-source-region map through whitespace normalization, reading-order
  reconstruction, multiline text, and chunking. Associate table labels and values spatially.
- Preserve low-confidence OCR results for uncertainty handling. The current OCR helper
  filters results at confidence <= 0.3, so its current behavior cannot be used unchanged.
- Process all pages and bounded overlapping text windows; merge duplicate/overlapping
  detections without losing occurrence identity. Test spans crossing window/page boundaries.
- Map detections to tight boxes with tested safety margins. Where OCR supplies only line
  boxes, refine to words/characters or visibly propose a broader uncertain box; do not pretend
  to have precise value boundaries.
- Flag low-quality or unexpectedly empty extraction. A genuinely blank page is valid;
  failed extraction is not evidence that a page contains no sensitive information.

The checkpoint configuration includes `max_len: 384` and `max_width: 12`; long inputs and
long entities need explicit boundary tests. Those values should not be presented as a simple
384-subtoken context guarantee. [Checkpoint configuration](https://huggingface.co/nvidia/gliner-PII/blob/main/gliner_config.json)

## Permanent export

Use installed PyMuPDF and Pillow to render pages, replace approved regions in the pixel
buffers with opaque black, then insert only those sanitized raster images into a new PDF.
Do not copy original PDF pages or insert a black overlay over source objects. Rendering
and image insertion are supported by the existing library. [PyMuPDF image documentation](https://pymupdf.readthedocs.io/en/latest/recipes-images.html)

- Process pages incrementally with bounded resolution, pixel count, page count, memory,
  and runtime. Choose resolution/file-size defaults using the feasibility results.
- Include visible annotations/form values in the canonical render so they can be reviewed.
- Re-encode sanitized images without source EXIF or image metadata. Do not carry original
  text layers, attachments, annotations, forms, metadata, thumbnails, or incremental history
  into the new document. Use a neutral download filename rather than copying a sensitive name.
- Verify the saved PDF can be reopened, preserves page order/dimensions, has no source
  text layer or attachments, and contains only the expected sanitized page images.
- Render the saved artifact again and verify approved regions are covered. OCR/known-value
  checks provide additional leakage detection, but a negative OCR result is not proof of safety.
- Atomically publish a verified artifact only. Failed/cancelled work must not become a
  downloadable “completed” export.

## Application integration

Follow the current registry and TaskRunner architecture rather than rebuilding orchestration.

| Area | Planned changes |
| --- | --- |
| Agent catalogue | Add `document_redaction` to backend/frontend target contracts, registry, labels, validation, and a new prompt manifest. GLiNER runs through its own local detector service, not an Ollama model entry. |
| Agent execution | The specialist starts/opens a redaction job and returns a job/workspace reference. Long work does not remain inside the synchronous `/tasks` request. |
| Persistence | Add a narrowly scoped redaction-job model/migration with owner, source ID/hash, policy, processing status, page findings/status, review revision/approval, cancellation state, and export reference. Keep large images/PDFs in private storage. |
| Worker | Follow the existing database-backed RAG worker lifecycle/claim pattern. Start with one active redaction job, offload blocking work, check cancellation between bounded units, and handle interrupted jobs explicitly on restart. No distributed queue dependency. |
| API | Add owner-scoped create/status, page preview/findings, review update, approve/export, cancel, and download operations under `/api/v1`. Use polling for progress initially. Validate revisions, coordinates, page bounds, ownership, and allowable state transitions server-side. |
| Frontend | Add a dedicated review workspace, reachable from the selected agent and document context. Render server page images with selectable boxes, zoom, page navigation, uncertainty indicators, manual controls, and keyboard-accessible review actions. |
| Storage/deletion | Tie artifacts and findings to their job/source lifecycle. Source deletion cancels related work and removes associated private artifacts without a worker recreating them afterward. Preserve existing original/RAG deletion rules and make retention behavior explicit. |
| Setup | Pin GLiNER and compatible dependencies in `uv.lock`; pin the model revision. Predownload detector/tokenizer/OCR assets during setup and check readiness. Runtime must use local assets and must not download silently. |

Important existing integration points:

- `backend/app/models/profile_schemas.py`, `backend/app/agents/registry.py`
- `backend/app/services/task_runner.py`, `backend/app/api/routes/tasks.py`
- `backend/app/api/routes/chat.py`, `backend/app/api/routes/documents.py`
- `backend/app/services/ocr.py`, `backend/app/services/rag_container_worker.py`
- `backend/app/models/db_models.py`, `backend/app/main.py`, `backend/alembic/versions/`
- `frontend/src/types/chat.ts`, `frontend/src/lib/schemas.ts`, `frontend/src/lib/constants.ts`
- `frontend/src/components/chat/ChatWindow.tsx`, `frontend/src/app/documents/page.tsx`

Preview images and findings contain sensitive information: enforce authenticated ownership
on every read/write/download, private non-cacheable responses, and storage outside the web
root. Validate file signatures and decoded resource limits even for previously uploaded files.
Reject unsupported/encrypted/unreadable inputs with actionable errors. Cancel/delete work
must prevent later publication, and policy edits must not race an export of stale boxes.

## Delivery milestones and verification

### Milestone 1 feasibility results

Measured on the Apple M1 Pro with 16 GiB unified memory using a synthetic two-page
personnel PDF, an image render of its first page, and no real personal data:

- Pinned `nvidia/gliner-PII` revision `bd23e8ef4425fd04e34c5204ab49ffaa706eae79`
  loaded successfully on CPU and MPS. First local load after download took about 8.4 s;
  the first download was 1.78 GB and took about 1 min 40 s. MPS and CPU returned identical
  predictions; warm inference averaged 0.128 s/page on MPS and 0.189 s/page on CPU.
- GLiNER returned 5 of 7 exact full-field values (0.714): both names were detected only
  as first names. Explicit field-label rules recovered 7 of 7 complete fixture values and
  mapped all seven GLiNER spans to page boxes. Keep both candidate sources; do not rely on
  GLiNER alone for field boundaries.
- The existing local Qwen 2.5 7B correctly selected the employee's name and retained the
  manager's name in 1.19 s. Ollama kept the 4.8 GB model loaded. The feasibility process
  peaked at 3.9 GB resident memory; total system memory pressure was not measured.
- At 300 DPI, EasyOCR identified all four field labels and all four line boxes aligned to
  their source regions after an 8-point margin. Exact value recall was 3 of 4 because OCR
  changed the email's period to a space at 0.951 confidence. Treat malformed structured
  values as uncertain candidates even when OCR confidence is high; mandatory review remains
  necessary. These measurements are from one fixture, not a general accuracy claim.
- The exported two-page image-only PDF reopened successfully, contained no selectable text,
  and rendered every approved test box as black pixels. This checks export mechanics; test
  boxes were generated from fixture ground truth rather than GLiNER detections.

This is sufficient to proceed with the extraction and detection milestone while retaining
the existing release gate: evaluate representative documents before claiming coverage.

| Milestone | Deliverable | Completion evidence |
| --- | --- | --- |
| 1. Feasibility and evaluation | A local prototype exercising extraction, GLiNER, rules, contextual reasoning, and raster export on synthetic labelled fixtures. | Measure CPU and supported MPS execution on the M1 Pro/16 GiB machine; report cold/warm latency, peak memory, per-category recall/precision, contextual errors, OCR alignment, and export results. Agree measured quality/resource thresholds before the full UI. If the candidate fails, evaluate another local detector and recheck model terms before selection. |
| 2. Extraction and detection | Complete-document geometry, validated policy, merged findings, explicit uncertainty/failure reporting. | Tests cover digital/scanned/mixed PDFs, tables, repeated values, identical names in different roles, rotated pages, multiline addresses, uncertain OCR, and boundary-spanning values. No silently skipped pages or truncated input. |
| 3. Jobs and export | Saved owned jobs, narrow worker, review revisions, cancellation/restart handling, fresh sanitized PDF generation. | Integration tests cover account isolation, restart recovery, stale revisions, deletion/export races, invalid boxes, failed pages, cancellations, metadata/attachment removal, and approved-pixel replacement. Inspect images extracted from saved outputs as well as rendered output. |
| 4. Review workspace and agent | End-to-end instructions, review, correction, approval, and download. | Component tests plus a focused Playwright flow: attach fixture, request employee-only redaction, correct a box, resolve a failed page, approve, and inspect the downloaded PDF. Verify zoom/rotation mapping and keyboard controls. |
| 5. Release readiness | Offline setup/readiness checks, calibrated defaults, documented coverage/limitations. | Run with networking disabled after setup; rerun the frozen evaluation corpus, focused existing agent/document/auth regressions, lint/type checks, and saved-artifact leakage checks. Document remaining measured misses; do not describe the model as guaranteeing complete PII removal. |

Separate detection quality from export correctness: all approved regions must be physically
removed from the exported artifact, while detection recall/precision must be measured against
ground truth, including false negatives. Passing an image-only/text-extraction check does not
prove all sensitive visible content was found. Runtime review remains mandatory.

## Implementation checkpoint and remaining work

Implemented: pinned local GLiNER setup, deterministic rules, contextual selection through
the existing local Qwen 2.5 7B Ollama service, PDF/image extraction with OCR, owner-scoped
queued jobs, progress/cancellation, saved review findings, manual boxes, revision-gated
approval, and verified image-only PDF export. The agent is available from the task/chat
catalogue and from the dedicated `/redaction` workspace. Source deletion removes related
job artifacts. Focused checks currently cover 107 backend cases; frontend TypeScript and
360 tests pass.

Known gaps before release: contextual instructions can now pause for a local-model question
and resume with the user's answer, but ambiguity detection still depends on the model response;
failed/unreadable pages fail the job rather than offering page retry or a page-specific
manual-resolution state; review does not yet filter by category; automated boxes can be
deselected and resized numerically, while manual boxes can be drawn; no Playwright end-to-end
or frozen representative evaluation corpus has run. Keep mandatory human review and do not
claim complete PII coverage until the evaluation corpus establishes per-category recall and
false-positive rates.

## Scope and next checkpoint

Batch support now accepts up to 20 owned documents with one shared policy, creates an
independent review job for each, shows per-document progress, and offers a ZIP after every
current review has been exported. Review and export remain per document; unattended batch
export is not supported.

Deferred: Office document inputs, multilingual automatic detection, automatic handwriting/
face/signature/barcode interpretation, unattended export, searchable output, and sanitizing
existing originals or RAG indexes.

The next checkpoint is release hardening: resolve the known gaps that affect review safety,
then run the frozen synthetic and representative evaluation corpus offline and inspect
saved exports for leakage. Office documents, multilingual detection, automatic
handwriting/face/signature/barcode interpretation, unattended export, searchable output, and
sanitizing existing originals or RAG indexes remain deferred.
