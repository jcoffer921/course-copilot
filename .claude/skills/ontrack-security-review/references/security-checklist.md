# OnTrack security checklist

## Identity

- Minimal OAuth scopes
- State and PKCE single-use
- Verified token claims
- Verified email
- Admission policy explicit
- Session fixation prevented
- POST + CSRF logout
- No unnecessary provider tokens at rest

## Object ownership

- Course
- Material and processing job
- Source preview and citation
- Cora session/message
- Flashcard/progress/review
- Quiz attempt and mastery
- Grade item
- Academic/custom event
- Notification
- Study session/activity
- Exam plan
- Saved site

For each resource: list, detail, create with parent, update, delete, bulk action, export, and worker publish.

## Input and storage

- Path-safe IDs
- Parser limits
- Private storage
- Atomic/versioned writes
- Corrupt versus missing data
- No unconfirmed overwrite
- No runtime course data committed
- Delete/export ownership

## AI boundary

- Uploaded prompt injection resisted
- Model JSON schema validated
- Citation allowlist enforced
- Unsupported answer refusal
- Web source visibly distinct
- Quotas and bounded retries

## Production

- Required secret key
- Debug disabled
- HTTPS and secure cookies
- Trusted hosts/origins
- Safe proxy configuration
- Postgres/object storage for multi-instance use
- Backups and restore test
- Private-data log scrubbing
