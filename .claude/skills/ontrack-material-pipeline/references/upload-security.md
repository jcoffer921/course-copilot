# Upload and artifact security

## Admission

- Explicit extension allowlist
- Declared MIME checked
- Magic/content signature checked
- Per-file and per-user size limits
- PDF page and extracted-text limits
- DOCX/PPTX archive expansion and entry limits
- Parser timeout and memory bounds
- Empty/encrypted/unreadable behavior defined

## Storage

- Server-generated opaque key
- Original filename stored only as sanitized display metadata
- Private storage by default
- Short-lived authorized download/preview only
- Encryption and backups provided by deployment storage
- Retention for failed, replaced, and deleted artifacts
- No durable dependence on container-local disk in multi-instance production

## Processing

- File text delimited as untrusted model input
- Strict output schema
- Context/token maximums
- Hash-based duplicate detection where appropriate
- Idempotency key and version/lease check
- Ownership re-check before every read and publish
- No raw text, prompts, tokens, or provider payloads in logs

## Review and publish

- Proposed versus active revision visible
- User can correct/include/exclude extracted fields
- No silent overwrite
- Calendar imports remain pending until confirmed
- Delete/replace impact enumerated before confirmation
