---
name: ontrack-page-migrator
description: Migrate one OnTrack top-level view from the legacy monolithic `agent/templates/agent/ontrack.html` controller into an authenticated, URL-addressable Django page with shared shell and app-owned JavaScript. Use for Dashboard, Courses, Cora, Calendar, Study, Settings, or course-workspace page extraction, direct-link/back-forward support, and legacy-view strangler migration. Preserve the current OnTrack design and never hand-edit generated `support.js` or `_ds/*` artifacts.
---

# OnTrack Page Migrator

Move one view at a time. Preserve behavior first; improve it in a later bounded change.

## Inventory the view

1. Read repository `AGENTS.md`, current page plan, `config/urls.py`, page view, `ontrack.html`, and relevant APIs/tests.
2. Read [references/page-inventory.md](references/page-inventory.md).
3. Map the target view's markup, styles, controller state, lifecycle hooks, event listeners, API calls, shared state, modals, and DOM selectors.
4. Identify dependencies on the generated DC runtime. Treat `agent/static/agent/support.js` and `_ds/*` as immutable generated inputs.
5. Record parity criteria before editing.

## Use the strangler pattern

- Add an authenticated named browser route for the target page.
- Render through `app_base.html` with shared sidebar/topbar/toast partials.
- Load only shared utilities plus the target page's app-owned JavaScript module.
- Use real `<a>` navigation, active-page state, and direct URLs.
- Preserve the legacy view behind a temporary internal/feature-flag route until parity is verified.
- Do not extract several major views in one change.

Recommended order: Dashboard, Courses, Cora, Calendar, Study, Settings. Course subpages follow Courses.

## Separate responsibilities

- Django page view: authentication and initial render context only.
- API: JSON data and mutations.
- Service: business rules and composition.
- Page module: interaction, state local to that page, rendering, and API calls.
- Shared modules: API wrapper, CSRF, navigation, modal, and toast behavior.

Do not copy business logic from the legacy controller into page JavaScript. Do not duplicate API helper implementations between pages.

## Preserve state and UX

- Encode meaningful selection in the URL where appropriate: course, session, week/date, topic, or exam.
- Make refresh, direct link, back, and forward work.
- Initialize and fetch only the active page.
- Preserve loading, empty, error, retry, confirmation, focus, and mobile states.
- Preserve OnTrack tokens, typography, spacing, sidebar dimensions, course colors, and Cora identity.
- Keep browser credentials server-side and retain CSRF protection.

## Verify parity

- Add route authentication/render tests.
- Compare old and new API request sequence and mutation effects.
- Exercise primary, empty, failure, and retry flows.
- Check direct refresh and history navigation.
- Check keyboard/focus and narrow widths.
- Check console and network panels.
- Run focused and full tests.

Only remove the legacy route/markup after every migrated page reaches parity and the user approves cutover.

## Report

List behavior moved, shared code introduced, legacy dependencies remaining, parity checks completed, and any intentionally deferred visual/product improvements.
