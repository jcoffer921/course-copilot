# Material processing states

| State | Meaning | Allowed next states |
| --- | --- | --- |
| `uploaded` | metadata and private original recorded | `queued`, `deleted` |
| `queued` | eligible background job exists | `processing`, `failed`, `deleted` |
| `processing` | one versioned job owns the lease | `needs_review`, `failed`, `deleted` |
| `needs_review` | validated proposal exists; not authoritative | `ready`, `queued`, `deleted` |
| `ready` | confirmed revision is published | `queued` replacement, `deleted` |
| `failed` | safe failure code stored | `queued`, `deleted` |
| `deleted` | tombstoned/retention pending | none without explicit restore design |

## Invariants

- Exactly one owner and course per material
- Job carries owner, material ID, and expected version
- Only current-version jobs may publish proposals
- Only validated proposals may enter `needs_review`
- Only explicit confirmation may publish
- Confirmation is atomic and idempotent
- Replacement never removes the active revision before publish
- Deletion/tombstone blocks late worker publication
- Retry creates/reuses one bounded job, not duplicate writes
- Safe error code is separate from private diagnostic detail
