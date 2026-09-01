import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";
import { showToast } from "./core/toast.js";
import { restoreFocus } from "./core/modal.js";
import { renderMarkdown } from "./core/markdown.js";
import { confirmDialog, promptDialog } from "./core/dialogs.js?v=20260901-1";

initNavigation();

const $ = id => document.getElementById(id);
const state = { courses: [], course: null, sessions: [], session: null, messages: [], sending: false, creating: false, requestId: null, retryQuestion: null, sourceTrigger: null, dismissedDeadlineAt: null };
const els = {
  loading: $("cora-loading"), error: $("cora-page-error"), empty: $("cora-empty-courses"), grid: $("cora-grid"),
  breadcrumb: $("cora-breadcrumb-course"), course: $("cora-course-select"), search: $("cora-search"), list: $("cora-session-list"),
  listEmpty: $("cora-session-empty"), searchEmpty: $("cora-search-empty"), messages: $("cora-messages"), newState: $("cora-new-state"),
  title: $("cora-page-title-live"), grounding: $("cora-grounding-course"), notice: $("cora-material-notice"), input: $("cora-input"),
  send: $("cora-send"), form: $("cora-composer"), mode: $("cora-grounding-mode"), courseOption: $("cora-course-option"), webOption: $("cora-web-option"), clip: $("cora-material-picker"), live: $("cora-live"), turnError: $("cora-turn-error"), retry: $("cora-retry"),
  source: $("cora-source-panel"), sourceLoading: $("cora-source-loading"), sourceError: $("cora-source-error"), sourceContent: $("cora-source-content"),
  sourceName: $("cora-source-name"), sourceMeta: $("cora-source-meta"), sourceExcerpt: $("cora-source-excerpt"), sourceIcon: $("cora-source-icon"), sourceOpen: $("cora-source-open"),
  menuButton: $("cora-session-menu-button"), menu: $("cora-session-menu"), newMessage: $("cora-new-message-indicator"), conversations: $("cora-conversations")
};

function setUrl({ push = false } = {}) {
  if (!state.course) return;
  const url = new URL(location.href); url.search = ""; url.searchParams.set("course", state.course.id);
  if (state.session) url.searchParams.set("session", state.session.session_id);
  history[push ? "pushState" : "replaceState"]({}, "", url);
}
function relativeTime(value) {
  const date = new Date(value), days = Math.floor((Date.now() - date.getTime()) / 86400000);
  if (days < 1) return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}
function setBusy(busy) { state.sending = busy; els.input.disabled = busy; els.send.disabled = busy || !els.input.value.trim(); }
function announce(text) { els.live.textContent = text; }
function nearBottom() { return els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight < 100; }
function scrollBottom(force = false) { if (force || nearBottom()) requestAnimationFrame(() => { els.messages.scrollTop = els.messages.scrollHeight; }); else els.newMessage.hidden = false; }
function closeSource() { els.source.hidden = true; els.grid.classList.remove("source-open"); restoreFocus(state.sourceTrigger); state.sourceTrigger = null; }

function createThinkingIndicator() {
  const article = document.createElement("article");
  article.className = "cora-message cora-message-assistant cora-thinking";
  article.setAttribute("role", "status");
  article.setAttribute("aria-label", "Cora is thinking");

  const meta = document.createElement("div");
  meta.className = "cora-message-meta";
  meta.textContent = "Cora";

  const bubble = document.createElement("div");
  bubble.className = "cora-message-bubble cora-thinking-bubble";
  const mark = document.createElement("span");
  mark.className = "cora-thinking-mark";
  mark.setAttribute("aria-hidden", "true");
  const activity = document.createElement("div");
  activity.className = "cora-thinking-activity";
  const dots = document.createElement("span");
  dots.className = "cora-thinking-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  const status = document.createElement("span");
  status.className = "cora-thinking-label";
  const phases = [
    "Reading your course materials",
    "Finding the most relevant notes",
    "Putting the answer together",
  ];
  let phase = 0;
  status.textContent = phases[phase];
  const timer = window.setInterval(() => {
    phase = (phase + 1) % phases.length;
    status.textContent = phases[phase];
  }, 1800);

  activity.append(dots, status);
  bubble.append(mark, activity);
  article.append(meta, bubble);
  return {
    element: article,
    stop() {
      window.clearInterval(timer);
      article.remove();
    },
  };
}

function renderSessions() {
  const query = els.search.value.trim().toLocaleLowerCase();
  const rows = state.sessions.filter(item => item.title.toLocaleLowerCase().includes(query));
  els.list.replaceChildren(); els.listEmpty.hidden = !!state.sessions.length || !!query; els.searchEmpty.hidden = !!rows.length || !query;
  for (const item of rows) {
    const button = document.createElement("button"); button.type = "button"; button.className = "cora-session-row";
    button.setAttribute("role", "option"); button.setAttribute("aria-selected", String(state.session?.session_id === item.session_id));
    const icon = document.createElement("span"); icon.className = "cora-session-icon"; icon.textContent = "◯";
    const copy = document.createElement("span"); copy.className = "cora-session-copy";
    const title = document.createElement("strong"); title.textContent = item.title;
    const time = document.createElement("small"); time.textContent = relativeTime(item.updated_at);
    copy.append(title, time); button.append(icon, copy); button.addEventListener("click", () => openSession(item.session_id, true)); els.list.append(button);
  }
}
function citationLabel(source) {
  if (typeof source === "string") return source;
  const details = [source.title]; if (source.page) details.push(`p. ${source.page}`); else if (source.chunk_id) details.push(source.chunk_id);
  return details.filter(Boolean).join(" · ");
}
function pendingDeadlineActions(message) {
  if (message.pending_deadlines?.length) return message.pending_deadlines;
  if (message.pending_deadline) return [message.pending_deadline];
  return [];
}

function describeDeadlineAction(item) {
  const when = item.time ? `${item.date} at ${item.time}` : item.date;
  if (item.action === "delete") return `Remove "${item.title}" — ${item.date}`;
  if (item.action === "update") return `Move "${item.title}" to ${when}`;
  return `Add "${item.title}" — ${when}`;
}

function confirmButtonLabel(items) {
  if (items.length > 1) return `Confirm all (${items.length})`;
  const action = items[0]?.action;
  return action === "delete" ? "Remove from calendar" : action === "update" ? "Update calendar" : "Add to calendar";
}

async function confirmDeadlineActions(items, button) {
  button.disabled = true;
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/sessions/${encodeURIComponent(state.session.session_id)}/deadlines/confirm/`, {
      method: "POST",
      body: JSON.stringify({ actions: items.map(item => ({
        action: item.action, event_id: item.event_id, course_id: item.course_id,
        title: item.title, date: item.date, time: item.time, end_time: item.end_time, type: item.type,
      })) }),
    });
    state.session = data; state.messages = data.messages || [];
    renderMessages(); await loadSessions(state.session.session_id); scrollBottom(true);
    showToast("Calendar updated.", "success");
  } catch (error) {
    button.disabled = false;
    showToast(error.message || "Couldn't update the calendar.", "error");
  }
}

function renderMessages() {
  els.messages.replaceChildren();
  if (!state.messages.length) { els.messages.append(els.newState); els.newState.hidden = false; return; }
  state.messages.forEach((message, messageIndex) => {
    const article = document.createElement("article"); article.className = `cora-message cora-message-${message.role}`;
    const meta = document.createElement("div"); meta.className = "cora-message-meta"; meta.textContent = `${message.role === "assistant" ? "Cora" : "You"}  ${message.timestamp ? relativeTime(message.timestamp) : "Now"}`;
    const bubble = document.createElement("div"); bubble.className = "cora-message-bubble";
    if (message.role === "assistant") bubble.append(renderMarkdown(message.content));
    else bubble.textContent = message.content;
    article.append(meta, bubble);
    if (message.role === "assistant") {
      if (!message.grounded) { const badge = document.createElement("p"); badge.className = "cora-ungrounded"; badge.textContent = "Not supported by the available course materials"; article.append(badge); }
      const pendingItems = pendingDeadlineActions(message);
      const isLatest = messageIndex === state.messages.length - 1;
      const isDismissed = state.dismissedDeadlineAt === state.messages.length;
      if (pendingItems.length && !(message.deadline_missing || []).length && isLatest && !isDismissed) {
        const card = document.createElement("div"); card.className = "cora-deadline-confirm";
        const list = document.createElement("ul");
        pendingItems.forEach(item => { const li = document.createElement("li"); li.textContent = describeDeadlineAction(item); list.append(li); });
        const actionsRow = document.createElement("div"); actionsRow.className = "cora-deadline-confirm-actions";
        const dismissBtn = document.createElement("button"); dismissBtn.type = "button"; dismissBtn.className = "btn btn-secondary"; dismissBtn.textContent = "Not now";
        dismissBtn.addEventListener("click", () => { state.dismissedDeadlineAt = state.messages.length; renderMessages(); });
        const confirmBtn = document.createElement("button"); confirmBtn.type = "button"; confirmBtn.className = "btn btn-primary"; confirmBtn.textContent = confirmButtonLabel(pendingItems);
        confirmBtn.addEventListener("click", () => confirmDeadlineActions(pendingItems, confirmBtn));
        actionsRow.append(dismissBtn, confirmBtn);
        card.append(list, actionsRow);
        article.append(card);
      }
      if (message.sources?.length) {
        const sources = document.createElement("div"); sources.className = "cora-sources"; const label = document.createElement("span"); label.textContent = "Sources"; sources.append(label);
        message.sources.forEach((source, citationIndex) => {
          if (typeof source === "string") { const legacy = document.createElement("span"); legacy.className = "cora-source-chip legacy"; legacy.textContent = source; sources.append(legacy); return; }
          const chip = document.createElement("button"); chip.type = "button"; chip.className = `cora-source-chip ${source.material_type === "web" ? "web" : ""}`;
          chip.textContent = `${source.material_type === "web" ? "Web · " : "▤  "}${citationLabel(source)}  ›`; chip.setAttribute("aria-label", `Open source preview for ${citationLabel(source)}`);
          chip.addEventListener("click", () => openSource(source, messageIndex, citationIndex, chip)); sources.append(chip);
        }); article.append(sources);
      }
      const actions = document.createElement("div"); actions.className = "cora-message-actions";
      const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy"; copy.setAttribute("aria-label", "Copy response");
      copy.addEventListener("click", async () => { await navigator.clipboard.writeText(message.content); showToast("Response copied.", "success"); }); actions.append(copy); article.append(actions);
    }
    els.messages.append(article);
  });
}
async function loadSessions(preferredSession, push = false) {
  state.sessions = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/sessions/`); renderSessions();
  const wanted = preferredSession || state.session?.session_id;
  if (wanted && state.sessions.some(item => item.session_id === wanted)) await openSession(wanted, push);
  else if (state.sessions[0]) await openSession(state.sessions[0].session_id, push);
  else { state.session = null; state.messages = []; renderMessages(); setUrl({ push }); }
}
async function selectCourse(id, { preferredSession = null, push = true, focusComposer = true } = {}) {
  const course = state.courses.find(item => item.id === id); if (!course) return;
  const draft = els.input.value; if (state.course && state.course.id !== id && draft.trim() && !(await confirmDialog({ title: "Switch courses?", message: "Your unsent draft will be discarded.", confirmLabel: "Switch course" }))) { els.course.value = state.course.id; return; }
  state.course = course; state.session = null; state.messages = []; els.input.value = ""; closeSource();
  els.breadcrumb.textContent = course.name; els.title.textContent = `Cora · ${course.name}`; els.grounding.textContent = `${course.name} course materials`;
  els.input.placeholder = `Ask a question about ${course.name}…`; els.course.value = course.id; els.notice.hidden = true;
  els.courseOption.textContent = `Grounded in ${course.name} course materials`; els.webOption.textContent = `Grounded in ${course.name} materials + approved web`;
  els.mode.value = "course_materials"; els.webOption.hidden = true;
  try { const [domains, sites] = await Promise.all([apiRequest(`/api/courses/${encodeURIComponent(course.id)}/domains/`), apiRequest(`/api/courses/${encodeURIComponent(course.id)}/saved-sites/`)]); els.webOption.hidden = !(domains.domains?.length || sites.sites?.length); } catch (_) { els.webOption.hidden = true; }
  if (course.is_draft || !course.materials?.count) { els.notice.hidden = false; els.notice.textContent = "No confirmed material is ready for new grounded questions. You can still review conversation history."; }
  setBusy(false); await loadSessions(preferredSession, push); if (focusComposer) els.input.focus();
}
async function openSession(id, push = false) {
  closeSource(); const data = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/sessions/${encodeURIComponent(id)}/`);
  state.session = data; state.messages = data.messages || []; renderSessions(); renderMessages(); setUrl({ push }); scrollBottom(true);
}
async function newSession() {
  if (!state.course || state.course.is_draft || !state.course.materials?.count) return showToast("Confirm course material before starting a new grounded conversation.", "error");
  if (state.creating) return;
  if (state.session && !state.messages.length) { els.input.focus(); return; }
  const existing = state.sessions.find(item => item.message_count === 0 && item.title === "New chat");
  if (existing) { await openSession(existing.session_id, true); els.input.focus(); return; }
  state.creating = true;
  try { const created = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/sessions/`, { method: "POST" }); await loadSessions(created.session_id, true); els.input.focus(); }
  finally { state.creating = false; }
}
function uuid() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-0000-4000-8000-${Math.random().toString(16).slice(2, 14)}`; }
async function send(question, requestId = uuid(), retry = false) {
  if (!state.session) await newSession(); if (!state.session) return;
  const follow = nearBottom(); state.requestId = requestId; state.retryQuestion = question; els.turnError.hidden = true;
  if (!retry) state.messages.push({ role: "user", content: question, timestamp: new Date().toISOString() }); renderMessages(); setBusy(true); announce("Cora is thinking."); if (follow) scrollBottom(true);
  const thinking = createThinkingIndicator(); els.messages.append(thinking.element);
  try {
    const result = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/ask/`, { method: "POST", body: JSON.stringify({ question, session_id: state.session.session_id, client_request_id: requestId, grounding_mode: els.mode.value }) });
    thinking.stop(); state.messages.push({ role: "assistant", content: result.answer, grounded: result.grounded, sources: result.sources || [], timestamp: new Date().toISOString() });
    state.retryQuestion = null; els.input.value = ""; renderMessages(); await loadSessions(state.session.session_id); announce("Cora answered."); scrollBottom(follow);
  } catch (error) { thinking.stop(); els.turnError.hidden = false; els.turnError.querySelector("span").textContent = error.message || "Cora is temporarily unavailable."; announce("Cora could not answer. You can retry."); }
  finally { thinking.stop(); setBusy(false); els.input.focus(); }
}
async function openSource(citation, messageIndex, citationIndex, trigger) {
  state.sourceTrigger = trigger; els.source.hidden = false; els.grid.classList.add("source-open"); els.sourceLoading.hidden = false; els.sourceError.hidden = true; els.sourceContent.hidden = true;
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/sources/preview/`, { method: "POST", body: JSON.stringify({ ...citation, session_id: state.session.session_id, message_index: messageIndex, citation_index: citationIndex }) });
    const source = data.source; els.sourceName.textContent = source.title; els.sourceExcerpt.textContent = source.excerpt;
    els.sourceMeta.textContent = [source.page ? `Page ${source.page}` : "", source.lecture_id || source.chunk_id || ""].filter(Boolean).join(" · "); els.sourceIcon.textContent = source.material_type === "web" ? "↗" : "▤";
    const downloadable = source.material_type !== "web" && /^[0-9a-f-]{36}$/i.test(source.material_id); els.sourceOpen.hidden = !downloadable;
    if (downloadable) els.sourceOpen.href = `/api/courses/${encodeURIComponent(state.course.id)}/materials/${encodeURIComponent(source.material_id)}/download/`;
    els.sourceLoading.hidden = true; els.sourceContent.hidden = false; $("cora-source-close").focus();
  } catch (error) { els.sourceLoading.hidden = true; els.sourceError.hidden = false; els.sourceError.textContent = error.message; }
}
async function menuAction(action) {
  els.menu.hidden = true; els.menuButton.setAttribute("aria-expanded", "false"); if (!state.session) return;
  if (action === "copy-link") { await navigator.clipboard.writeText(location.href); return showToast("Conversation link copied.", "success"); }
  if (action === "rename") { const title = await promptDialog({ kicker: "Cora conversation", title: "Rename conversation", message: "Choose a title that will be easy to find later.", inputLabel: "Conversation title", defaultValue: state.session.title, confirmLabel: "Save title" }); if (!title) return; await apiRequest(`/api/courses/${state.course.id}/sessions/${state.session.session_id}/`, { method: "PATCH", body: JSON.stringify({ title }) }); await loadSessions(state.session.session_id); }
  if (action === "delete" && await confirmDialog({ kicker: "Permanent action", title: `Delete “${state.session.title}”?`, message: "This conversation will be permanently removed. Your course materials will not be deleted.", confirmLabel: "Delete conversation", danger: true })) { const deletedId = state.session.session_id; await apiRequest(`/api/courses/${state.course.id}/sessions/${deletedId}/`, { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) }); state.session = null; state.sessions = state.sessions.filter(item => item.session_id !== deletedId); await loadSessions(state.sessions[0]?.session_id, true); }
}

els.form.addEventListener("submit", event => { event.preventDefault(); const question = els.input.value.trim(); if (question && !state.sending) send(question); });
els.input.addEventListener("input", () => { els.send.disabled = state.sending || !els.input.value.trim(); els.input.style.height = "auto"; els.input.style.height = `${Math.min(140, els.input.scrollHeight)}px`; });
els.input.addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); els.form.requestSubmit(); } });
els.course.addEventListener("change", () => selectCourse(els.course.value)); els.search.addEventListener("input", renderSessions); $("cora-clear-search").addEventListener("click", () => { els.search.value = ""; renderSessions(); els.search.focus(); });
$("cora-new-session").addEventListener("click", () => newSession().catch(error => showToast(error.message, "error"))); els.retry.addEventListener("click", () => send(state.retryQuestion, state.requestId, true));
$("cora-source-close").addEventListener("click", closeSource); els.newMessage.addEventListener("click", () => { els.newMessage.hidden = true; scrollBottom(true); });
els.messages.addEventListener("scroll", () => { if (nearBottom()) els.newMessage.hidden = true; });
els.menuButton.addEventListener("click", () => { els.menu.hidden = !els.menu.hidden; els.menuButton.setAttribute("aria-expanded", String(!els.menu.hidden)); });
els.menu.addEventListener("click", event => { const action = event.target.closest("button")?.dataset.action; if (action) menuAction(action).catch(error => showToast(error.message, "error")); });
els.clip.addEventListener("click", () => showToast(`Cora automatically uses confirmed materials from ${state.course?.name || "this course"}. Add or review files on the course Materials page.`, "info"));
$("cora-open-conversations").addEventListener("click", () => els.conversations.classList.add("open")); $("cora-close-conversations").addEventListener("click", () => els.conversations.classList.remove("open"));
document.querySelectorAll(".cora-prompt-examples button").forEach(button => button.addEventListener("click", () => { els.input.value = button.textContent; els.input.dispatchEvent(new Event("input")); els.input.focus(); }));
document.addEventListener("keydown", event => { if (event.key === "Escape" && !els.source.hidden) closeSource(); });
els.mode.addEventListener("change", () => { document.querySelector(".cora-grounding-badge").lastChild.textContent = els.mode.value === "course_materials_and_web" ? "Course materials + approved web" : "Course materials only"; });
window.addEventListener("popstate", () => { const url = new URL(location.href), course = url.searchParams.get("course"), session = url.searchParams.get("session"); if (course) selectCourse(course, { preferredSession: session, push: false }).catch(() => {}); });

(async function init() {
  try {
    const payload = await apiRequest(($("cora-workspace").dataset.coursesUrl));
    const pages = await Promise.all((payload.semesters || []).filter(term => term.id !== payload.semester?.id).map(term => apiRequest(`${$("cora-workspace").dataset.coursesUrl}?semester=${encodeURIComponent(term.id)}`)));
    const byId = new Map(); [payload, ...pages].flatMap(page => page.courses || []).filter(item => !item.archived).forEach(item => byId.set(item.id, item)); state.courses = [...byId.values()];
    els.loading.hidden = true; if (!state.courses.length) { els.empty.hidden = false; return; } els.grid.hidden = false;
    for (const course of state.courses) { const option = document.createElement("option"); option.value = course.id; option.textContent = course.name; els.course.append(option); }
    const url = new URL(location.href), requested = url.searchParams.get("course"), selected = state.courses.some(item => item.id === requested) ? requested : state.courses[0].id;
    await selectCourse(selected, { preferredSession: url.searchParams.get("session"), push: false, focusComposer: false });
    if (window.ONTRACK_INITIAL_QUESTION) { els.input.value = window.ONTRACK_INITIAL_QUESTION; els.input.dispatchEvent(new Event("input")); }
  } catch (error) { els.loading.hidden = true; els.error.hidden = false; els.error.textContent = error.message || "Cora could not load."; }
})();
