# Cross-layer feature checklist

Use only the applicable sections.

## Discovery

- Existing service or partial implementation found
- Data source and source of truth identified
- User ownership path identified
- API and browser consumers identified
- Saved-data/API compatibility assessed
- Generated files excluded from manual edits

## Contract

- Inputs and defaults defined
- Success response defined
- `400`, `401`, `404`, `409`, `429`, and provider-failure behavior considered
- Idempotency/retry behavior defined
- Destructive behavior requires explicit confirmation
- Grounding/citation behavior defined for AI output

## Implementation

- Business logic in service layer
- Serializer validates boundary input
- View/command remains thin
- Blocking work kept off ASGI event loop
- Authenticated owner passed through every layer
- No secrets or private content logged
- Existing behavior preserved or migrated intentionally

## Verification

- Happy path
- Invalid/malformed input
- Missing resource
- Foreign-owned resource
- Corrupt/legacy data
- Duplicate/retry behavior
- Focused tests
- Full suite
- Browser/API/CLI smoke test
- Documentation updated
