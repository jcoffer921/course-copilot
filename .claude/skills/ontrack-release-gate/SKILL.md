---
name: ontrack-release-gate
description: Evaluate an OnTrack/Course Copilot implementation branch before the user creates a pull request. Use for final readiness checks, milestone completion audits, regression/security/migration verification, production configuration review, documentation drift checks, or requests asking whether a branch is ready to merge or release. Produce a ready/not-ready report; never create, submit, or merge the PR unless explicitly requested.
---

# OnTrack Release Gate

Judge evidence from the branch and tests. Do not equate a clean diff or passing unit tests with release readiness.

## Establish the baseline

1. Read repository `AGENTS.md`, the implementation plan, `README.md`, `CLAUDE.md`, and migration notes.
2. Confirm the intended base branch and obtain the base/head commit range.
3. Inspect working-tree status and the complete diff, including migrations, environment examples, generated files, and removed files.
4. Read [references/release-checklist.md](references/release-checklist.md) and select all applicable gates.
5. Do not modify, commit, push, create a PR, or merge during a review-only request.

## Review the change

- Map each plan acceptance criterion to code and verification evidence.
- Identify unrelated changes, missing migrations, stale compatibility paths, and generated/runtime/private data.
- Confirm every new private resource has list/detail/mutation/worker ownership coverage.
- Confirm Google sign-in permissions match the approved identity policy.
- Confirm uploads, AI outputs, citations, destructive actions, quotas, and logs follow OnTrack security rules.
- Confirm schema/API changes preserve or explicitly migrate old data and consumers.
- Confirm no dashboard/page owns business logic that belongs in a service.

Use `@ontrack-security-review` for a focused security pass and `@ontrack-two-user-test` when ownership coverage is incomplete.

## Run verification

Run the safest applicable checks in this order:

1. Focused tests for changed areas.
2. Full `python -m pytest agent/tests/ -q`.
3. Django migration consistency and `manage.py check`.
4. `manage.py check --deploy` with production-like settings when available.
5. ASGI server/API smoke tests.
6. Browser checks for changed pages at desktop and narrow widths.
7. Console/network inspection.
8. Migration dry run against a copy of representative current data.
9. Secret/private-data/runtime-file inspection.

Never run destructive migrations on real data merely to satisfy the gate. If credentials or a safe environment are unavailable, mark the gate unverified.

## Decide readiness

Set **Not ready** when any of these remain:

- failing required test;
- known cross-user access;
- broader-than-approved OAuth scope or unnecessary token storage;
- destructive migration without dry-run/rollback/backup path;
- private/runtime data or secret committed;
- unconfirmed AI extraction becoming authoritative;
- broken grounding/citation contract;
- undocumented breaking API/schema change;
- production deployment depends on ephemeral local state;
- required acceptance criterion lacks evidence.

Warnings may remain only when they are explicitly documented, non-security-critical, and outside the approved scope.

## Report

Use this structure:

```text
Release status: Ready | Not ready

Blocking findings:
Verification performed:
Tests and results:
Security and ownership:
Migrations and compatibility:
UI/accessibility smoke checks:
Deployment/privacy readiness:
Documentation:
Known limitations:
Required actions before PR:
```

Include commands and exact results. Separate failures from skips and unverified checks. When ready, provide a concise PR-ready change summary for the user to reuse, but do not create the PR.
