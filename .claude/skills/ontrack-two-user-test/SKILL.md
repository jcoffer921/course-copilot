---
name: ontrack-two-user-test
description: Create or review two-user ownership and IDOR regression tests for private OnTrack resources. Use whenever adding or changing a course, material, job, citation, Cora session, flashcard, quiz attempt, mastery score, grade, event, notification, study session, exam plan, saved site, export, deletion, bulk action, or nested API endpoint. Also use after fixing a cross-user data leak.
---

# OnTrack Two-User Test

Prove that authenticated ownership is enforced at every layer and operation.

## Discover the resource contract

1. Read repository `AGENTS.md` and the affected service, serializer, view, URL, model/storage helper, and existing tests.
2. Identify the stable resource ID, parent IDs, owner field/path, list endpoint, detail endpoint, mutations, bulk actions, and worker paths.
3. Read [references/ownership-matrix.md](references/ownership-matrix.md) and select every applicable row.

## Build isolated fixtures

- Create User A and User B with authenticated test clients.
- Create the target resource for User A through the lowest reliable public/service interface.
- Create same-slug or similar resources for User B when collision behavior matters.
- Redirect `storage.COURSES_DIR` to `tmp_path` for filesystem-backed data.
- Do not read or mutate checked-in course data.
- Keep all Anthropic/Google/network calls mocked.

## Test the matrix

For each supported operation, assert:

1. User A can perform the authorized action.
2. User B cannot list or discover User A's resource.
3. User B cannot retrieve it by a known identifier.
4. User B cannot mutate, delete, complete, sync, retry, export, or publish it.
5. User B cannot create a child under User A's parent.
6. The denial does not reveal whether the foreign resource exists; prefer `404` for object lookups.
7. User A's resource remains unchanged after every denied request.

Test the service/storage function directly when it is callable independently of HTTP. An API-only denial is insufficient if a worker or service lookup remains unscoped.

## Check nested and asynchronous paths

- Validate both child ownership and parent ownership.
- Reject valid child IDs paired with a foreign course/material/session.
- Ensure queued jobs persist owner and resource version.
- Re-check ownership/state immediately before a worker publishes output.
- Ensure deletion/tombstone behavior prevents late worker writes.
- Ensure list counts, errors, and timing do not expose foreign resources unnecessarily.

## Avoid weak tests

- Do not test only unauthenticated requests.
- Do not rely only on random UUID unguessability.
- Do not assert merely that the response is “not 200”; assert the exact contract.
- Do not reuse one client while switching user objects implicitly.
- Do not omit post-denial integrity checks.
- Do not create `user=None` fixtures unless explicitly testing a legacy migration.

## Verify and report

Run the focused ownership file and relevant endpoint/service suite. Report covered operations, exact denials, untested paths, and any discovered authorization defect. Do not weaken production behavior to make a test pass.
