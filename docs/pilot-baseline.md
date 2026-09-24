# Pilot baseline capture

OnTrack has no in-app onboarding survey yet, and building one is out of scope
for pre-pilot week (redeploy risk, no time to test it end to end). Baseline
has to be captured before a student's first sign-in or it's gone for good —
so this is captured externally, once, outside the app.

## Why this can't wait for an in-app flow

`UserSettings` currently only records an optional free-text `cohort` string,
set once at signup from `?cohort=` on the sign-in-start URL (see
`agent/auth_views.py::google_login_start`). There is no year-in-school, no
pre-tool confidence/organization rating, and no learning-style field anywhere
in the schema. Once a student signs in, "before OnTrack" is gone — there's no
way to reconstruct it retroactively, and it's the only thing that lets the
pilot report say "OnTrack changed X" instead of just "X was true in week 6."

## 1. External form (Google Form / Typeform) — 6 questions

Keep it to these six. Every one either supplies the join key or measures
something OnTrack claims to move; nothing is "nice to know."

1. **Full name** — free text. For the pilot report only; not the join key.
2. **School email address** — free text, required.
   *Must match the email you'll use to sign in to OnTrack with Google* — this
   is the join key against `/api/analytics/export/`'s `email` column (see
   §3 below).
3. **What year are you in school?** — multiple choice: First-year /
   Sophomore / Junior / Senior / Graduate or professional / Other
4. **This week, how on top of your deadlines and coursework do you feel?**
   — 1–5 scale (1 = Completely behind, 5 = Fully on top of everything)
5. **How confident do you feel about managing your coursework this
   semester?** — 1–5 scale (1 = Not at all confident, 5 = Very confident)
6. **Which one best describes how you learn new material best?** — multiple
   choice: Reading/writing notes · Watching or listening (video, recorded
   lecture) · Hands-on practice/quizzing myself · Visual (diagrams, charts) ·
   Talking it through with others

Deliberately cut from this list: current GPA, which specific courses, study
hours/week. None of them are needed to answer "did OnTrack help," and every
extra question loses respondents.

## 2. Invite email draft

The form must be completed *before* the sign-in link is used, and the
sign-in link must carry the cohort tag so `UserSettings.cohort` gets set
automatically — students should never have to type a cohort code by hand
(typos silently drop them out of the cohort). That's why the link below
points at `/accounts/login/start/?cohort=...` (which reads `cohort` straight
off the query string) rather than the branded `/signup/` page (whose cohort
field is a manually-typed text box with no auto-fill from the URL).

> **Subject: One 2-minute form before your OnTrack account — [Course/Cohort name]**
>
> Hi [First name],
>
> You're one of the students piloting OnTrack this semester. Before your
> account is set up, we need two minutes of your time — a short baseline
> survey that lets us actually measure whether the tool helps.
>
> **Step 1 — Complete the baseline form (required, ~2 minutes):**
> [FORM_LINK]
>
> **Step 2 — Sign in with your school Google account:**
> https://[ONTRACK_BASE_URL]/accounts/login/start/?cohort=[COHORT_CODE]
>
> Please do Step 1 before Step 2 — the form only takes a couple of minutes,
> and it's the only chance we get to record where you're starting from.
>
> Use the *same school email* on both steps so we can match your answers to
> your account.
>
> Questions? Just reply to this email.
>
> — The OnTrack team

Replace `[FORM_LINK]`, `[ONTRACK_BASE_URL]`, and `[COHORT_CODE]` per cohort
batch. `[COHORT_CODE]` should be short and stable (e.g. `fall26-cs101`), and
distinct per class/section if the pilot report needs to break results out
that way — `agent/services/analytics.py` groups nothing by cohort today, but
the raw column is there once you want to.

## 3. Analytics export join key — verified and fixed

`GET /api/analytics/export/` (`agent/services/analytics.py::build_student_export`
/ `render_student_csv`) is gated by `PilotOwnerPermission`
(`agent/authentication.py::is_pilot_owner`), which raises `404` for anyone
but the configured `ONTRACK_PILOT_OWNER_EMAIL` — confirmed by
`agent/tests/test_analytics.py::test_analytics_is_owner_only_at_page_api_export_and_navigation`
and re-verified by reading the permission class directly. This export is a
pre-existing owner-only surface; adding fields to it is not a new privacy
exposure.

**Before this change**, the export had no `email` and no `cohort` column —
only `student_id` (an internal DB primary key), which cannot be joined
against a Google Form response. **Fixed**: both columns are now the second
and third columns in the CSV (`student_id, email, cohort, account_status,
...`), sourced directly from `student.email` and `student.settings.cohort`.
Covered by an updated assertion in `test_export_is_per_student_private_and_date_scoped`.

## Explicitly not built this session

- No in-app onboarding screen, modal, or profile-page baseline form.
- No new database field for the survey answers themselves — they live in the
  external form's own response sheet, joined to OnTrack data by email only
  when someone runs the analysis. This keeps the redeploy surface at zero for
  pilot week.
