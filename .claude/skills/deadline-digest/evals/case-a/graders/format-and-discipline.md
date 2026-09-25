---
type: llm
criteria: "Does the digest follow source discipline (dates array only, no inference), surface the recent past-due item, flag the near-term exam distinctly, and stay factual rather than editorializing?"
focus: last_message
---

Full points only if the response:
- Includes all three date entries with date, title, and type, sorted chronologically, leading with the soonest
- Surfaces the past-due Homework 2 (due yesterday, not marked complete) rather than silently dropping it since it's still recent
- Flags the Midterm Exam (due tomorrow) distinctly as urgent/near-term (e.g. "due tomorrow"), not buried as a plain date entry indistinguishable from the others
- Does NOT invent or infer any deadline not in the dates array (e.g. does not guess at a reading assignment or problem set "probably" due around this time)
- Does NOT editorialize about workload or stress (no "that's a lot due this week!" or similar commentary) — states the facts and lets the student assess their own load
- Does not attempt to write anything to disk or mention triggering a calendar sync — this skill is read-only digest generation only

Zero points if it drops the past-due Homework 2 silently, invents a deadline not in the source data, or adds workload commentary.
