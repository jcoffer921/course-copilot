# Cora Chat Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Cora a visual presence in the Chat tab — a sage avatar mark on her chat bubbles, and the same mark pulsing while a reply is loading.

**Architecture:** Everything lives in one file, `agent/templates/agent/ontrack.html` — a single Django template that renders a `dc-runtime` single-page app (custom `<x-dc>`/`sc-if`/`sc-for` tags parsed by the prebuilt `support.js` bundle into a React tree). There is no separate frontend build step for this file: it's edited directly and served as-is. Two small additions: a `.cora-avatar` CSS class (in the template's own inline `<style>` block, not the generated design-system stylesheet) and new markup in the Chat tab's message list and loading indicator that reuses it.

**Tech Stack:** Django template, inline CSS, the project's `dc-runtime` component syntax (`sc-if`, `sc-for`, `{{ }}` bindings resolved by `renderVals()` in the page's own `<script type="text/x-dc">` block).

## Global Constraints

- Avatar mark: 28px circle, background `var(--color-accent-2)` (the design system's sage second-accent color), containing the same spark glyph used for the sidebar's brand mark at 14px, in white — not a new icon.
- No message-grouping / "once per run" logic — every assistant bubble gets its own avatar (confirmed dead-code otherwise: `ask.py:201-204` always appends exactly one `user` then one `assistant` message per turn, so consecutive same-role messages cannot occur).
- No avatar or mark on user messages — unchanged (right-aligned, solid terracotta).
- New CSS goes in `ontrack.html`'s own inline `<style>` block (inside `<helmet>`), **not** in the generated design-system stylesheet (`agent/static/agent/_ds/organic-.../styles.css`), which is regenerated from `theme.json` by an external design-sync tool and could silently drop hand-added rules.
- Scope is the Chat tab only — no changes to the sidebar, other tabs, or existing copy strings.
- No automated frontend test suite exists for this template (it's plain markup + inline JS, no JS test runner in the repo). Verification in every task below is manual: run the dev server, drive the page in a browser, confirm the described visual behavior.

---

### Task 1: Cora avatar on assistant chat bubbles

**Files:**
- Modify: `agent/templates/agent/ontrack.html:16-22` (inline `<style>` block)
- Modify: `agent/templates/agent/ontrack.html:461-485` (chat message list markup)
- Modify: `agent/templates/agent/ontrack.html:990-992` (`msgStyle` JS function)

**Interfaces:**
- Consumes: the existing `m.isAssistant` boolean already computed per-message in `renderVals()` (`agent/templates/agent/ontrack.html:1002`, `isAssistant: m.from === 'assistant'`) — no new JS field needed for this task.
- Produces: a `.cora-avatar` CSS class, reused by Task 2 for the loading indicator.

- [ ] **Step 1: Add the `.cora-avatar` CSS rule**

In `agent/templates/agent/ontrack.html`, the inline `<style>` block currently reads:

```html
  <style>
    body{margin:0;background:var(--color-bg);color:var(--color-text);font-family:var(--font-body)}
    a{color:var(--color-accent-700)}
    a:hover{color:var(--color-accent-800,var(--color-accent-700))}
    ::-webkit-scrollbar{width:8px;height:8px}
    ::-webkit-scrollbar-thumb{background:var(--color-neutral-300);border-radius:99px}
  </style>
```

Change it to:

```html
  <style>
    body{margin:0;background:var(--color-bg);color:var(--color-text);font-family:var(--font-body)}
    a{color:var(--color-accent-700)}
    a:hover{color:var(--color-accent-800,var(--color-accent-700))}
    ::-webkit-scrollbar{width:8px;height:8px}
    ::-webkit-scrollbar-thumb{background:var(--color-neutral-300);border-radius:99px}
    .cora-avatar{width:28px;height:28px;border-radius:999px;background:var(--color-accent-2);display:flex;align-items:center;justify-content:center;flex:none}
  </style>
```

- [ ] **Step 2: Give assistant message rows a gap and top alignment**

In the same file, find `msgStyle` (currently at `agent/templates/agent/ontrack.html:990-992`):

```javascript
    const msgStyle = (from) => from === 'user'
      ? { display: 'flex', justifyContent: 'flex-end' }
      : { display: 'flex', justifyContent: 'flex-start' };
```

Change it to:

```javascript
    const msgStyle = (from) => from === 'user'
      ? { display: 'flex', justifyContent: 'flex-end' }
      : { display: 'flex', justifyContent: 'flex-start', alignItems: 'flex-start', gap: '10px' };
```

This adds the row-level gap between the new avatar and the message bubble, and keeps the avatar pinned to the top of the row instead of stretching to the bubble's full height. User rows are untouched.

- [ ] **Step 3: Add the avatar to the message list markup**

Find the chat message list block (currently at `agent/templates/agent/ontrack.html:461-485`):

```html
            <sc-for list="{{ chatMessages }}" as="m" hint-placeholder-count="4">
              <div style="{{ m.rowStyle }}">
                <div style="{{ m.wrapStyle }}">
                  <div style="{{ m.bubbleStyle }}">{{ m.text }}</div>
                  <sc-if value="{{ m.isAssistant }}" hint-placeholder-val="{{ false }}">
                    <div style="font-size:11px;opacity:.5;margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;align-items:center">
                      <sc-if value="{{ m.hasSources }}" hint-placeholder-val="{{ false }}">
                        <span>Sources:</span>
                        <sc-for list="{{ m.sourceItems }}" as="src" hint-placeholder-count="1">
                          <sc-if value="{{ src.isLink }}" hint-placeholder-val="{{ false }}">
                            <a href="{{ src.href }}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline">{{ src.text }}</a>
                          </sc-if>
                          <sc-if value="{{ src.isPlain }}" hint-placeholder-val="{{ true }}">
                            <span>{{ src.text }}</span>
                          </sc-if>
                        </sc-for>
                      </sc-if>
                      <sc-if value="{{ m.notGroundedText }}" hint-placeholder-val="{{ false }}">
                        <span>{{ m.notGroundedText }}</span>
                      </sc-if>
                    </div>
                  </sc-if>
                </div>
              </div>
            </sc-for>
```

Change it to (only the new `<sc-if>` block right after the opening `rowStyle` div is new):

```html
            <sc-for list="{{ chatMessages }}" as="m" hint-placeholder-count="4">
              <div style="{{ m.rowStyle }}">
                <sc-if value="{{ m.isAssistant }}" hint-placeholder-val="{{ false }}">
                  <div class="cora-avatar">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg>
                  </div>
                </sc-if>
                <div style="{{ m.wrapStyle }}">
                  <div style="{{ m.bubbleStyle }}">{{ m.text }}</div>
                  <sc-if value="{{ m.isAssistant }}" hint-placeholder-val="{{ false }}">
                    <div style="font-size:11px;opacity:.5;margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;align-items:center">
                      <sc-if value="{{ m.hasSources }}" hint-placeholder-val="{{ false }}">
                        <span>Sources:</span>
                        <sc-for list="{{ m.sourceItems }}" as="src" hint-placeholder-count="1">
                          <sc-if value="{{ src.isLink }}" hint-placeholder-val="{{ false }}">
                            <a href="{{ src.href }}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline">{{ src.text }}</a>
                          </sc-if>
                          <sc-if value="{{ src.isPlain }}" hint-placeholder-val="{{ true }}">
                            <span>{{ src.text }}</span>
                          </sc-if>
                        </sc-for>
                      </sc-if>
                      <sc-if value="{{ m.notGroundedText }}" hint-placeholder-val="{{ false }}">
                        <span>{{ m.notGroundedText }}</span>
                      </sc-if>
                    </div>
                  </sc-if>
                </div>
              </div>
            </sc-for>
```

The SVG path is copied verbatim from the sidebar brand mark (`agent/templates/agent/ontrack.html:31`), just at 14px instead of 18px, inside the 28px `.cora-avatar` circle instead of the 34px sidebar one.

- [ ] **Step 4: Start the dev server**

Run: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8010 --noreload` (Windows; adjust the interpreter path per `scripts/run_server.sh` on other platforms) from the `course-copilot` project root.

Expected: server starts and logs `Starting development server at http://127.0.0.1:8010/`.

- [ ] **Step 5: Manually verify the avatar on a live reply**

In a browser, open `http://127.0.0.1:8010/`, click **Ask Cora**, type any question into the input, and submit it (the request doesn't need to succeed for this check — a sage 28px circle with a white spark glyph should appear at the top-left of Cora's reply bubble once one renders; if the request errors, that's fine, this step only checks the avatar chrome, not the answer content).

Expected: the avatar is sage-colored, sized visibly smaller than the sidebar's brand mark, top-aligned with the first line of the bubble text; the user's own message bubble (sent just before) has no avatar and stays right-aligned in terracotta, unchanged from before this change.

- [ ] **Step 6: Manually verify the avatar on a loaded past session**

In the same browser session, click **+ New chat**, ask a second question, then look at the **Past chats** list in the left panel and click an earlier session to reload it.

Expected: every historical assistant message in the reloaded session also shows the avatar — this exercises `openChatSession`'s message load path (`agent/templates/agent/ontrack.html` `openChatSession`, ~line 627), not just the live `sendChatMessage` path, and both should render through the same `chatMessages` mapping in `renderVals()` without further changes.

- [ ] **Step 7: Stop the dev server**

Stop the process started in Step 4 (e.g. `Ctrl+C` in its terminal, or kill the PID if it was started in the background).

- [ ] **Step 8: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Add Cora avatar to assistant chat bubbles

Gives Cora a visual presence in the transcript: a sage 28px circle
with the sidebar's spark glyph, recolored, on every assistant bubble.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Pulsing avatar on the "Thinking…" indicator

**Files:**
- Modify: `agent/templates/agent/ontrack.html:16-23` (inline `<style>` block, as modified by Task 1)
- Modify: `agent/templates/agent/ontrack.html:487-489` (`chatLoading` markup)

**Interfaces:**
- Consumes: the `.cora-avatar` class produced by Task 1 (must be completed first).
- Produces: `.cora-avatar.pulsing` modifier class and `@keyframes cora-pulse`, scoped to this file only.

- [ ] **Step 1: Add the pulsing animation CSS**

After Task 1, the inline `<style>` block ends with:

```html
    .cora-avatar{width:28px;height:28px;border-radius:999px;background:var(--color-accent-2);display:flex;align-items:center;justify-content:center;flex:none}
  </style>
```

Change it to:

```html
    .cora-avatar{width:28px;height:28px;border-radius:999px;background:var(--color-accent-2);display:flex;align-items:center;justify-content:center;flex:none}
    .cora-avatar.pulsing{animation:cora-pulse 1.6s ease-in-out infinite}
    @keyframes cora-pulse{
      0%,100%{box-shadow:0 0 0 0 color-mix(in srgb, var(--color-accent-2) 45%, transparent)}
      50%{box-shadow:0 0 0 6px color-mix(in srgb, var(--color-accent-2) 0%, transparent)}
    }
  </style>
```

- [ ] **Step 2: Update the `chatLoading` indicator markup**

Find (currently at `agent/templates/agent/ontrack.html:487-489`):

```html
          <sc-if value="{{ chatLoading }}" hint-placeholder-val="{{ false }}">
            <div style="padding:0 var(--space-6) var(--space-2);font-size:12.5px;opacity:.6">Thinking…</div>
          </sc-if>
```

Change it to:

```html
          <sc-if value="{{ chatLoading }}" hint-placeholder-val="{{ false }}">
            <div style="padding:0 var(--space-6) var(--space-2);display:flex;align-items:center;gap:10px">
              <div class="cora-avatar pulsing">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg>
              </div>
              <span style="font-size:12.5px;opacity:.6">Thinking…</span>
            </div>
          </sc-if>
```

The "Thinking…" copy itself is unchanged — it's now next to the avatar instead of alone.

- [ ] **Step 3: Start the dev server**

Run: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8010 --noreload` from the `course-copilot` project root (same as Task 1 Step 4).

- [ ] **Step 4: Manually verify the pulse**

Open browser devtools, go to the Network tab, and set throttling to **Slow 3G** (or similar) so the loading window is long enough to observe. Reload `http://127.0.0.1:8010/`, open **Ask Cora**, submit any question.

Expected: while the request is in flight, a sage `.cora-avatar` circle appears next to the "Thinking…" text and visibly pulses — a soft ring expands outward from the circle and fades, looping roughly every 1.6 seconds. Once the response resolves (or errors), the indicator disappears as before.

- [ ] **Step 5: Reset network throttling and stop the dev server**

Set devtools Network throttling back to **No throttling**. Stop the dev server process from Step 3.

- [ ] **Step 6: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Pulse Cora's avatar during the chat loading state

The "Thinking..." indicator now shows the same avatar mark with a
soft pulsing ring, so Cora reads as active while a reply is pending
instead of leaving the text to carry that alone.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
