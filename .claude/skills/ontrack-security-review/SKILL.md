---
name: ontrack-security-review
description: Audit OnTrack/Course Copilot changes for authentication, authorization, IDOR, OAuth, uploads, path traversal, secret/token handling, privacy, logging, AI abuse, destructive operations, and deployment hardening. Use before or after changes to accounts, courses, materials, Cora sessions, citations, grades, calendar events, study data, background jobs, storage, or production configuration. Use for review and findings; do not silently implement fixes unless requested.
---

# OnTrack Security Review

Review evidence first and report exploitable behavior, not generic warnings.

## Scope the review

1. Read repository `AGENTS.md` and affected plans/contracts.
2. Inspect the diff plus the complete authorization path: route, serializer, view, service, ORM/file lookup, background job, and browser call.
3. Identify assets, actors, trust boundaries, identifiers, and destructive actions.
4. Read [references/security-checklist.md](references/security-checklist.md) for applicable checks.

## Review priorities

### Authentication and OAuth

- Require Django authentication for every private page/API.
- Keep Google sign-in identity-only unless a separate optional integration is explicitly requested.
- Verify OAuth state, PKCE, ID token audience, expiry, issuer, and `email_verified`.
- Never log or persist authorization codes, ID tokens, or identity-flow access/refresh tokens unnecessarily.
- Keep logout and other state changes POST-only with CSRF protection.

### Authorization and isolation

- Trace `request.user` into every query and path resolution.
- Treat a foreign-owned identifier as not found; do not leak existence.
- Check nested relationships: resource ID alone is insufficient if its course/material/session belongs to another user.
- Re-check ownership and resource state inside workers immediately before publishing results.
- Flag nullable private ownership and ambiguous legacy rows.

### Files and uploads

- Validate extension, MIME, magic/content, size, page count, and archive expansion.
- Use sanitized display names and server-generated storage keys.
- Prevent traversal and direct private-object exposure.
- Treat document text as untrusted data, not model instructions.
- Keep failed/replaced/deleted artifacts subject to an explicit retention policy.

### AI, privacy, and abuse

- Validate structured model output and citation IDs against supplied context.
- Prevent web/general content from masquerading as course material.
- Scrub private content, prompts, and credentials from logs/errors.
- Check per-user quotas, concurrency, retry bounds, and duplicate submission controls.
- Require explicit confirmation for destructive/bulk writes and external side effects.

### Deployment

- Check production secrets, `DEBUG`, hosts/origins, HTTPS, secure cookies, HSTS, proxy headers, database/storage durability, backups, and error scrubbing.

## Validate suspected findings

- Cite the exact code path and preconditions.
- Reproduce safely with a focused test or request when possible.
- Distinguish confirmed vulnerabilities from defense-in-depth improvements.
- Do not access or expose real user content to prove a finding.

## Output

Return findings first, ordered by severity:

```text
Severity: Critical | High | Medium | Low
Finding:
Affected path:
Evidence:
Attack/failure scenario:
Impact:
Recommended fix:
Required regression test:
```

Then list reviewed areas with no finding, assumptions, and remaining unverified surfaces. If no findings exist, say so directly and still report test coverage gaps.
