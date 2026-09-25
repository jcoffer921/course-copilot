# Ownership test matrix

| Operation | User A | User B | Integrity assertion |
| --- | --- | --- | --- |
| List | resource included | resource excluded | counts contain no leak |
| Detail GET | `200` | `404` | body reveals nothing |
| Child create | succeeds | `404` foreign parent | no foreign child created |
| PATCH/PUT | succeeds | `404` | original unchanged |
| DELETE | succeeds | `404` | original still exists |
| Bulk action | owned items only | foreign IDs ignored/rejected | no foreign mutation |
| Retry/process | job starts | `404` | no foreign job created |
| Worker publish | owned/version-current | owner/state mismatch aborts | no late artifact |
| Source preview | bounded excerpt | `404` | no title/excerpt leak |
| Export | owned archive | no foreign bytes | archive scoped |
| Account/course deletion | exact owner tree | cannot target other user | unrelated data intact |

## Parent-child combinations

Test at least:

- owned parent + owned child;
- owned parent + foreign child ID;
- foreign parent + owned-looking child ID;
- same course slug for two users;
- deleted/archived parent with late child operation;
- legacy/null owner only during an explicit migration test.

## OnTrack resource families

- Course and filesystem/artifact namespace
- Material and processing job
- Citation/source preview
- Cora session/message
- Flashcard/progress/review
- Quiz attempt/mastery
- Grade item/configuration
- Academic/custom event and Calendar action
- Notification
- Study session/activity
- Exam plan/guide/practice set
- Saved site/trusted domain
