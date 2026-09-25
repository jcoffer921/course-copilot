# OnTrack release checklist

## Branch and scope

- Correct base/head recorded
- Working tree understood
- Diff matches approved milestones
- No unrelated refactor
- No generated runtime edited manually
- No automatic PR/merge

## Tests

- Focused suites pass
- Full suite passes
- Live-provider tests run or explicitly skipped
- Test count has not silently dropped
- Two-user matrix covers changed resources
- Retry/idempotency tests cover background work

## Security and privacy

- Identity-only Google scopes unless separate approved connection
- No unnecessary OAuth tokens at rest
- Authenticated ownership everywhere
- Upload limits and private storage
- Grounding/citation validation
- CSRF and destructive confirmation
- Rate/concurrency/cost limits
- Logs/errors scrub private content
- Export/delete behavior verified
- No secrets or runtime course data committed

## Data and migrations

- Model/schema migrations committed
- Dry run and idempotence
- Ambiguous legacy data reported, not guessed
- Compatibility reader/cutover defined
- Rollback and backup instructions
- Late-worker/deletion behavior
- Production durability defined

## UI and API

- Stable status codes/shapes
- Direct routes and refresh/history
- Loading/empty/error/retry
- Desktop and narrow widths
- Keyboard/focus/contrast
- Console/network clean
- Dashboard facts match source services

## Deployment and docs

- Production settings validated
- PostgreSQL/object storage/background worker gate addressed as applicable
- Backups/restore documented
- README, CLAUDE, AGENTS, env example, schemas, and commands accurate
- Known limitations and deferred scope documented
