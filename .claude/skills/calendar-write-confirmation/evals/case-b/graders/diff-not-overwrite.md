---
type: llm
criteria: "Does the response distinguish the update (with an old-value-to-new-value diff) from the addition, and pause for confirmation on both, rather than silently overwriting or duplicating?"
focus: last_message
---

Two different change categories are present: (1) an UPDATE to an existing synced event (midterm moved from Oct 14 to Oct 21), and (2) a brand-new ADDITION (Homework 5, never synced before). Per this skill, these must be shown as distinct categories, and the update specifically must show old value → new value, not a silent overwrite or a duplicate new event alongside the stale one.

Full points only if the response:
- Shows the midterm change explicitly as an update with both the old date (Oct 14) and new date (Oct 21) visible — not just silently presenting "Midterm Exam: Oct 21" with no mention that Oct 14 was the prior value
- Does not propose creating a second, duplicate "Midterm Exam" event alongside the old one
- Shows Homework 5 as a clearly separate, new addition (not conflated with the update)
- Still pauses for confirmation before making either change — does not claim either change has already been applied
- Does not treat the update as lower-risk than it is; deletions/updates to existing user calendar state should be called out as the more sensitive category, per this skill's guidance

Zero points if the response silently replaces the midterm event without showing the old value, or claims changes are already applied.
