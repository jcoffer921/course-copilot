# Cora chat avatar — design

## Context

The [OnTrack/Cora rebrand](2026-08-17-ontrack-cora-rebrand-design.md) gave the chat UI Cora's name in copy (placeholder, empty state, grounding text) but explicitly left "new UI elements... introducing Cora" out of scope. As a result, Cora's replies render as a plain neutral-gray bubble — visually indistinguishable from a generic system message, with nothing tying the conversation to the named assistant the copy already refers to. This pass adds Cora a visual presence in the chat transcript: a small avatar mark on her messages, and a livelier "thinking" state while a reply is in flight.

Two things were deliberately cut from scope during design:

1. **No message grouping.** The obvious pattern (Slack/iMessage-style — avatar once per run of consecutive same-sender messages) was considered and prototyped, but the backend only ever appends messages in strict `user`, `assistant`, `user`, `assistant`, … order (`agent/services/ask.py:201-204` always appends exactly one of each per turn; nothing in `sessions.py` can produce two consecutive same-role entries). A "first-of-run" check would be unreachable code under every real code path today, so it's dropped — the avatar simply renders on every assistant bubble, which is visually identical to "once per run" given strict alternation. If a future feature breaks that alternation (multi-part answers, a retry-without-reask flow), grouping can be revisited then.
2. **No changes beyond the Chat tab.** No new sidebar branding, no empty-state icon, no other tab touched — the rebrand spec's "no new UI elements" boundary still holds everywhere except this one specific gap (an assistant persona with literally no avatar in the one place avatars normally go).

## What changes and why

### 1. The mark

A 28px circle in `--color-accent-2` (the design system's sage "second voice," already used per-course as PSYC201's identity color) containing the same spark glyph used for the sidebar's brand mark, at 14px, in white. Reusing the exact glyph (not a new icon) reads as "the same brand mark, recolored for the assistant" rather than introducing a second unrelated icon to maintain. 28px was chosen over a 34px option (matching the sidebar mark's size 1:1) because at chat-column width the larger size competed with the message text — the mockup comparison confirmed 28px reads as a quiet detail, not a competing focal point.

New reusable class in the template's existing inline `<style>` block (`agent/templates/agent/ontrack.html`, the block already carrying `body{...}`, `a{...}`, `::-webkit-scrollbar{...}` overrides inside `<helmet>`):

```css
.cora-avatar{width:28px;height:28px;border-radius:999px;background:var(--color-accent-2);display:flex;align-items:center;justify-content:center;flex:none}
```

This lives in the page's own style block rather than the generated design-system stylesheet (`_ds/organic-.../styles.css`) — that file is the output of a design-sync tool and documents itself as regenerated from `theme.json`; a hand-added app-specific class there risks being silently dropped on the next sync. The page-level `<style>` block is already the established place for this project's own overrides.

### 2. Placement in the message list

Every assistant bubble gets the avatar to its left, top-aligned with the bubble's first line. User bubbles are unchanged — no avatar, right-aligned, solid terracotta, exactly as today.

Implementation touches `agent/templates/agent/ontrack.html` in two spots:

- **The `chatMessages` row markup** (`isChat` panel, the `sc-for list="{{ chatMessages }}"` block): each assistant row (`m.isAssistant`, an existing computed field) gets a `.cora-avatar` div inserted before the existing message-wrap div, with the SVG glyph inline. The row's flex container needs `gap:10px` and `alignItems:'flex-start'` added (currently only `display`/`justifyContent`) so the avatar sits flush against the bubble's top-left instead of stretching. No new field is needed on the `chatMessages` JS mapping (`renderVals()`, ~line 1000) — `m.isAssistant` already exists and is exactly the condition for showing the avatar.
- **No grouping/spacer logic** — per the scope decision above, every assistant row independently renders its own avatar.

### 3. Thinking state

The existing loading indicator (`chatLoading`, currently a bare `<div>Thinking…</div>` beneath the message list) becomes a row containing the same `.cora-avatar` mark — with a `.pulsing` modifier — next to the unchanged "Thinking…" text:

```css
.cora-avatar.pulsing{animation:cora-pulse 1.6s ease-in-out infinite}
@keyframes cora-pulse{
  0%,100%{box-shadow:0 0 0 0 color-mix(in srgb, var(--color-accent-2) 45%, transparent)}
  50%{box-shadow:0 0 0 6px color-mix(in srgb, var(--color-accent-2) 0%, transparent)}
}
```

A soft ring breathes outward from the avatar and fades, looping — reads as "she's active" without introducing a new loading pattern (no skeletons, no spinners) or touching the "Thinking…" copy itself.

## Explicitly out of scope for this pass

- Message grouping / "once per run" avatar suppression (see Context — currently unreachable given strict message alternation).
- Any avatar or mark on user messages.
- Sidebar, empty-state copy, or any tab other than Chat.
- Editing the generated design-system stylesheet (`_ds/organic-.../styles.css`) — new rules go in the page's own `<style>` block instead.
- Unrelated existing inconsistencies noted in the earlier UI review (hardcoded `#fff` values, the unstyled file input, `justify-content:between`) — separate cleanup, not part of this change.

## Verification

- Load `/`, open the Chat tab, ask a question: confirm Cora's reply bubble shows the sage avatar with the white spark glyph, top-aligned to the left of the bubble; confirm the user's own bubble is unchanged (no avatar, right-aligned, terracotta).
- While the request is in flight, confirm the "Thinking…" row shows the same avatar with a visibly pulsing ring, and that the text is unchanged.
- Ask a second question in the same session and confirm the pattern repeats identically for the new exchange (no stale grouping state carried over).
- Open a past chat session (sidebar "Past chats" list) with existing history and confirm every historical assistant message renders with the avatar — this exercises the `openChatSession` load path, not just live `sendChatMessage` replies.
- Visual check against both light-mode rendering only (the Organic system has no dark-mode tokens) at the app's normal viewport width.
