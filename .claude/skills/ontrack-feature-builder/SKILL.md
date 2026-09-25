---
name: ontrack-feature-builder
description: Build or change a feature in the OnTrack/Course Copilot Django repository through its service-first architecture. Use for new product behavior, API-backed UI work, feature extensions, bug fixes that cross service/view/frontend boundaries, or requests to implement a milestone from an OnTrack plan. Do not use for review-only, release-only, page-extraction-only, or upload-pipeline-only work when a more specific OnTrack skill applies.
---

# OnTrack Feature Builder

Implement one bounded OnTrack behavior while preserving grounding, ownership, async execution, and CLI/API parity.

## Start

1. Read repository `AGENTS.md`, current `README.md`, `CLAUDE.md`, and the relevant implementation plan.
2. Inspect the existing feature path before proposing files. Search the service, serializer, view, URL, page/template, app-owned JavaScript, tests, and documentation.
3. State the requested outcome, current behavior, affected contracts, and definition of done.
4. Identify whether a specialized skill also applies:
   - security or ownership: use `@ontrack-security-review` during validation;
   - cross-user tests: use `@ontrack-two-user-test`;
   - page extraction: use `@ontrack-page-migrator`;
   - material ingestion: use `@ontrack-material-pipeline`;
   - final branch readiness: use `@ontrack-release-gate`.

Read [references/feature-checklist.md](references/feature-checklist.md) when the change touches more than one application layer or alters a stored/API contract.

## Design the change

- Reuse existing services and data shapes before creating new ones.
- Put business rules, storage, Anthropic calls, parsing, and composition in `agent/services/`.
- Keep DRF serializers responsible for request validation.
- Keep API views and management commands thin.
- Make the web and CLI paths call the same service when both exist.
- Obtain Anthropic clients/models only through `agent/services/client.py`.
- Preserve ASGI behavior. Wrap blocking ORM/file operations appropriately in async call paths.
- Treat uploaded text and model output as untrusted data.
- Require an authenticated owner for every private resource and every background job.
- Preserve current response fields unless an explicit compatibility plan covers consumers and saved data.
- Do not modify generated `agent/static/agent/support.js` or `_ds/*` artifacts by hand.

## Implement incrementally

1. Add or update the smallest service contract.
2. Add serializer and API/CLI adapters.
3. Add or update the browser consumer.
4. Add tests at the lowest layer that owns each rule.
5. Add compatibility reads/migrations before switching writers when a schema changes.
6. Update documentation in the same change when architecture, schemas, environment variables, or commands change.

Do not mix unrelated refactors into the feature. Do not overwrite real course data during development or testing.

## Verify

- Run focused tests for touched services and endpoints.
- Run ownership tests for every new identifier or resource.
- Run the full `agent/tests/` suite when feasible.
- Smoke-test the affected page/API/CLI path.
- For UI work, verify loading, empty, error, retry, keyboard, mobile-width, console, and network states.
- Report commands run, results, skips, and anything not verified.

## Hand off

Summarize behavior delivered, contracts changed, migrations, security controls, tests, and remaining risks. Do not create a PR, merge, or push unless the user explicitly requests it.
