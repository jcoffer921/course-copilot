---
name: ontrack-material-pipeline
description: Design, implement, debug, or review OnTrack ingestion for syllabi, notes, slides, references, rubrics, and other student-uploaded course materials. Use for upload validation, private storage, processing jobs, PDF/DOCX/PPTX/TXT/MD extraction, Anthropic parsing, status polling, extraction review, confirmation, retries, replacement, deletion, material metadata, or migration from direct-write workflows.
---

# OnTrack Material Pipeline

Build a reviewable state machine. Never let upload or AI success silently become trusted academic data.

## Establish the contract

1. Read repository `AGENTS.md`, current schemas, storage/extraction services, serializers, views, tests, and material UI.
2. Identify the material kind, accepted formats, authoritative output, reviewable fields, and replacement behavior.
3. Read [references/processing-states.md](references/processing-states.md) for lifecycle rules.
4. Read [references/upload-security.md](references/upload-security.md) when accepting files or publishing stored artifacts.

## Use the lifecycle

Implement transitions through service methods, not arbitrary field updates:

`uploaded → queued → processing → needs_review → ready`

Allow `failed → queued` retry and explicit deletion. Require idempotency for upload registration, job execution, confirmation, and retry.

- Store original upload metadata and immutable/versioned proposed output.
- Keep the last confirmed revision active while a replacement is processing.
- Publish one validated revision atomically after user confirmation.
- Ensure unconfirmed syllabus dates do not become live calendar events.
- Record safe machine-readable error codes; do not expose provider traces or document text.

## Separate layers

- Material metadata: mutable operational state and ownership.
- Artifact store: private original and versioned derived bytes/JSON.
- Extraction service: deterministic text extraction plus model call where needed.
- Job: bounded orchestration, retries, state transitions, and version check.
- Review API/UI: editable proposed fields and confirmation.
- Published course schema: existing validated content contract.

Keep local and object storage behind one adapter. Do not expose filesystem paths or raw private object URLs.

## Secure the boundary

- Validate extension, declared MIME, detected content, size, page count, and archive expansion.
- Sanitize display filenames and generate storage identifiers server-side.
- Treat file text as untrusted data and delimit it from system instructions.
- Enforce owner/course/material relationships at request and worker time.
- Bound parsing, model context, retries, concurrency, and total user storage.
- Scrub private content from logs, metrics, and user-facing errors.
- Prevent late worker output after deletion, replacement, or version change.

## Preserve compatibility

When migrating from direct writes:

1. Add readers/metadata around existing artifacts.
2. Import with dry-run and an idempotent manifest.
3. Write proposed revisions through the new pipeline.
4. Cut over readers only after parity.
5. Avoid indefinite dual writes.

## Test

- valid supported file;
- unsupported/deceptive type;
- empty, corrupt, oversized, or expansion-bomb input;
- path-safe identifiers and filenames;
- duplicate request/job delivery;
- provider/parser timeout and malformed model JSON;
- user isolation for material, status, preview, retry, confirm, and delete;
- concurrent confirmation;
- deletion/replacement during processing;
- failed replacement preserves confirmed revision;
- unconfirmed dates remain outside the live calendar.

Run focused and full tests. Report lifecycle transitions exercised, storage behavior, limits, ownership coverage, and unverified live-provider cases.
