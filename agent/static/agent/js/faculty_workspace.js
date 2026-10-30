import { apiRequest } from "./core/api.js";
import { getCsrfToken } from "./core/csrf.js";
import { confirmDialog } from "./core/dialogs.js";
import { showToast } from "./core/toast.js";
import { runImportFlow } from "./faculty_import_flow.js";
import { HEADER_MAX_LENGTH, normalizeHeaderLine, workingMessage } from "./faculty_progress.js";
import { renderMarkdown } from "./core/markdown.js";
import { categoryCoverage, courseCategoryMap, planSummary, prerequisiteConflicts, suggestFollowUps } from "./faculty_plan_model.js";

const root = document.getElementById("fw-root");
const program = JSON.parse(document.getElementById("fw-active-program")?.textContent || "null");
const requirements = program?.requirements || null;

const one = selector => root?.querySelector(selector);

const EXPORT_FORMAT_KEY = "ontrack.facultyExportFormat";
const CHAT_WIDE_KEY = "ontrack.facultyChatWide"; // layout preference only; never student data
const EXPORT_LAYOUTS = ["term_table", "year_grid", "plan_notes"];
function preferredExportFormat() {
  try {
    const stored = localStorage.getItem(EXPORT_FORMAT_KEY);
    return EXPORT_LAYOUTS.includes(stored) ? stored : "term_table";
  } catch { return "term_table"; }
}

function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  for (const child of children) node.append(child);
  return node;
}

// ---- program picker (works with or without an active program) ----
const picker = one("[data-fw-program-picker]");
picker?.addEventListener("change", () => {
  const url = new URL(window.location.href);
  if (picker.value) url.searchParams.set("program", picker.value);
  else url.searchParams.delete("program");
  window.location.assign(url);
});

// ---- requirements import (drop zone or file picker) ----
const importInput = one("[data-fw-import-input]");

async function startImport(file) {
  if (!file) return;
  try {
    const confirmed = await runImportFlow({
      file,
      importUrl: root.dataset.importUrl,
      confirmUrl: root.dataset.confirmUrl,
      onChooseAnother: () => importInput?.click(),
    });
    if (confirmed) window.location.assign(`${window.location.pathname}?program=${encodeURIComponent(confirmed.requirement_id)}`);
  } catch (error) {
    showToast(error.message || "Import failed.", "error");
  }
}

importInput?.addEventListener("change", () => {
  const [file] = importInput.files;
  importInput.value = "";
  startImport(file);
});

root?.querySelectorAll("[data-fw-import-trigger]").forEach(trigger => {
  trigger.addEventListener("click", () => importInput?.click());
  trigger.addEventListener("dragover", event => { event.preventDefault(); trigger.classList.add("is-dragging"); });
  trigger.addEventListener("dragleave", () => trigger.classList.remove("is-dragging"));
  trigger.addEventListener("drop", event => {
    event.preventDefault();
    trigger.classList.remove("is-dragging");
    startImport(event.dataTransfer?.files?.[0]);
  });
});

// ---- session store: this tab's copy of the student state (sessionStorage), expiring like the server's ----
const SESSION_KEY = root?.dataset.sessionKey || "ontrack.facultySession";
const TEMPLATE_KEY = root?.dataset.templateKey || "ontrack.selectedFacultyTemplate";
// Same idle window as the server-side cache (data-state-ttl, in seconds); 30 minutes if the page omits it.
const stateTtl = (Number(root?.dataset.stateTtl) || 1800) * 1000;
const emptyState = () => ({ programId: program?.requirement_id || null, chatMessages: [], generatedPlan: null, dismissed: [] });

function readStored() {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
    const fresh = value && value.programId === program?.requirement_id
      && typeof value.savedAt === "number" && Date.now() - value.savedAt <= stateTtl;
    if (fresh) return value;
    if (value) sessionStorage.removeItem(SESSION_KEY); // expired or for another program: discard the student text now
  } catch { /* unreadable storage falls through to a fresh session */ }
  return null;
}

const sessionStore = {
  read() {
    const value = readStored();
    return value ? { ...emptyState(), ...value } : emptyState();
  },
  write(state) {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ...state, savedAt: Date.now() })); } catch { /* storage unavailable */ }
  },
  clear() {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* storage unavailable */ }
  },
  hasState() {
    return readStored() !== null;
  },
};

if (root && program) {
  let state = sessionStore.read();

  // The server keeps planning state until it is reset; this tab only keeps its own copy. If this tab has
  // no state for this program (new tab, other program), purge whatever the server still holds so the next
  // student never inherits the previous student's context.
  async function resetStaleServerSession() {
    try { await apiRequest(root.dataset.resetUrl, { method: "POST" }); }
    catch { /* best effort: New session resets again */ }
  }
  if (!sessionStore.hasState()) resetStaleServerSession();
  const creditsByCode = {};
  const titlesByCode = {};
  for (const category of requirements.categories || []) {
    for (const course of category.courses || []) {
      creditsByCode[course.code] = Number(course.credits) || 0;
      titlesByCode[course.code] = course.title || "";
    }
  }
  const categoryByCode = courseCategoryMap(requirements);

  const planBody = one("[data-fw-plan-body]");
  const planEmpty = one("[data-fw-plan-empty]");
  const chat = one("[data-fw-chat]");
  const issuesBox = one("[data-fw-issues]");
  const form = one("[data-fw-chat-form]");
  const input = one("#fw-chat-input");

  const persist = () => sessionStore.write(state);

  function renderCoverage() {
    const box = one("[data-fw-coverage]");
    box.replaceChildren();
    for (const row of categoryCoverage(state.generatedPlan, requirements)) {
      const full = row.creditsRequired > 0 && row.plannedCredits >= row.creditsRequired;
      const width = row.creditsRequired > 0 ? Math.min(100, Math.round((row.plannedCredits / row.creditsRequired) * 100)) : 0;
      const bar = el("div", { className: "fw-bar" }, [el("span", { attrs: { style: `width:${width}%` } })]);
      box.append(el("div", { className: `fw-cov-row${full ? " is-full" : ""}` }, [
        el("span", { className: "fw-cov-name", text: row.name || "Uncategorized" }),
        bar,
        el("em", { text: `${row.plannedCredits}/${row.creditsRequired}` }),
      ]));
    }
    if (!box.children.length) box.append(el("p", { className: "fw-muted", text: "This program has no requirement groups." }));
  }

  function renderSuggestions() {
    one("[data-fw-suggestions]").replaceChildren(...suggestFollowUps(state.generatedPlan, requirements).map(item => {
      const chip = el("button", { text: item.label, attrs: { type: "button", title: item.prompt } });
      chip.addEventListener("click", () => {
        input.value = item.prompt; // fills the box; the faculty member decides whether to send it
        autoGrow();
        input.focus();
      });
      return chip;
    }));
  }

  function renderPlan() {
    const draft = state.generatedPlan;
    planEmpty.hidden = Boolean(draft);
    planBody.hidden = !draft;
    renderCoverage();
    renderSuggestions();
    if (!draft) return;

    const conflicts = prerequisiteConflicts(draft, requirements);
    const summary = planSummary(draft, requirements);
    one("[data-fw-plan-title]").textContent = `Academic plan: ${draft.student_major || requirements.program_name || program.program_name}`;
    one("[data-fw-plan-notes]").textContent = draft.notes || "";

    const stats = [
      ["Planned credits", summary.plannedCredits],
      ["Terms", summary.termCount],
      ["Program credits", summary.programCredits],
      ["Needs attention", summary.issueCount],
    ];
    one("[data-fw-summary]").replaceChildren(...stats.map(([label, value]) =>
      el("div", { className: `fw-stat${label === "Needs attention" && value > 0 ? " is-warn" : ""}` }, [
        el("b", { text: String(value) }), el("small", { text: label }),
      ])));

    const conflictKeys = new Set(conflicts.map(c => `${c.semesterLabel}|${c.code}`));
    const prerequisiteFor = new Map(conflicts.map(c => [`${c.semesterLabel}|${c.code}`, c.prerequisite]));
    const terms = (draft.semesters || []).map(semester => {
      const courses = semester.courses || [];
      const termCredits = courses.reduce((sum, course) => sum + (creditsByCode[course.code] ?? (Number(course.credits) || 0)), 0);
      const head = el("tr", {}, ["Course", "Title", "Type", "Credits"].map(label => el("th", { text: label })));
      const rows = courses.length
        ? courses.map(course => {
            const key = `${semester.label}|${course.code}`;
            const titleCell = el("td", { text: course.title || titlesByCode[course.code] || "" });
            if (conflictKeys.has(key)) titleCell.append(" ", el("span", { className: "fs-chip is-warn", text: `Prereq: ${prerequisiteFor.get(key)}` }));
            return el("tr", { className: conflictKeys.has(key) ? "is-flagged" : "" }, [
              el("td", { className: "fw-code", text: course.code || "" }),
              titleCell,
              el("td", {}, [el("span", { className: "fs-chip", text: categoryByCode[course.code] || "Other" })]),
              el("td", { className: "fw-num", text: String(creditsByCode[course.code] ?? (Number(course.credits) || 0)) }),
            ]);
          })
        : [el("tr", {}, [el("td", { text: "No courses listed.", attrs: { colspan: "4" } })])];
      return el("section", { className: "fw-term" }, [
        el("h4", {}, [semester.label || "Term", el("span", { text: ` ${termCredits} credits` })]),
        el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]),
      ]);
    });
    one("[data-fw-term-list]").replaceChildren(...terms);
    renderIssues(conflicts);
  }

  function renderIssues(conflicts) {
    const visible = conflicts.filter(c => !state.dismissed.includes(`${c.code}|${c.prerequisite}`));
    issuesBox.hidden = visible.length === 0;
    issuesBox.replaceChildren(...visible.map(conflict => {
      const dismiss = el("button", { className: "fs-btn", text: "Dismiss", attrs: { type: "button" } });
      dismiss.addEventListener("click", () => {
        state.dismissed.push(`${conflict.code}|${conflict.prerequisite}`);
        persist();
        renderIssues(prerequisiteConflicts(state.generatedPlan, requirements));
      });
      return el("div", { className: "fw-issue" }, [
        el("b", { text: "Needs attention" }),
        el("p", { text: `${conflict.code} (${conflict.semesterLabel}) needs ${conflict.prerequisite} in an earlier term.` }),
        dismiss,
      ]);
    }));
  }

  function renderMessages() {
    chat.replaceChildren(el("div", { className: "fw-msg is-assistant", text: "Tell me about the student: their major and any coursework already completed. I will draft a plan from this program's requirements." }));
    const lastIndex = state.chatMessages.length - 1;
    state.chatMessages.forEach((message, index) => {
      const bubble = el("div", { className: `fw-msg ${message.role === "user" ? "is-user" : "is-assistant"}${message.error ? " is-error" : ""}` });
      if (message.role === "assistant" && !message.error) {
        bubble.classList.add("fw-md");
        bubble.append(renderMarkdown(message.content)); // builds DOM nodes from text; no HTML string is ever parsed
      } else {
        bubble.textContent = message.content;
      }
      const retryable = index === lastIndex && message.error && !message.noRetry && state.chatMessages[index - 1]?.role === "user";
      if (retryable) {
        const retry = el("button", { className: "fs-btn fw-retry", text: "Retry", attrs: { type: "button", "data-fw-retry": "" } });
        retry.addEventListener("click", () => sendMessage(state.chatMessages[index - 1].content, { retry: true }));
        bubble.append(el("div", { className: "fw-msg-actions" }, [retry]));
      }
      chat.append(bubble);
    });
    chat.scrollTop = chat.scrollHeight;
  }

  function addMessage(role, content, error = false, retryable = true) {
    state.chatMessages.push({ role, content, ...(error ? { error: true } : {}), ...(error && !retryable ? { noRetry: true } : {}) });
    persist();
    renderMessages();
  }

  // ---- the "Cora is working" indicator ----
  const statusRegion = one("[data-fw-status]");
  const announce = text => { if (statusRegion) statusRegion.textContent = text; };
  let thinking = null;

  function showThinking() {
    const label = el("span", { className: "fw-thinking-label" });
    const dots = el("span", { className: "fw-dots", attrs: { "aria-hidden": "true" } }, [el("i"), el("i"), el("i")]);
    const node = el("div", { className: "fw-msg is-assistant is-thinking", attrs: { "data-fw-thinking": "" } }, [dots, label]);
    const started = Date.now();
    const tick = () => { label.textContent = workingMessage((Date.now() - started) / 1000); };
    tick();
    chat.append(node);
    chat.scrollTop = chat.scrollHeight;
    announce("Cora is working on your plan.");
    thinking = { node, timer: window.setInterval(tick, 1000) };
  }

  function hideThinking() {
    if (!thinking) return;
    window.clearInterval(thinking.timer);
    thinking.node.remove();
    thinking = null;
  }

  // ---- template handoff from the Templates tab ----
  function selectedTemplate() {
    try {
      const value = JSON.parse(sessionStorage.getItem(TEMPLATE_KEY) || "null");
      return value && typeof value.name === "string" && Array.isArray(value.terms) ? value : null;
    } catch { return null; }
  }

  function renderTemplateBanner() {
    const banner = one("[data-fw-template-banner]");
    const template = selectedTemplate();
    banner.hidden = !template;
    if (!template) return;
    one("[data-fw-template-name]").textContent = template.name;
    if (!input.value) {
      input.value = `Use the ${template.name} as the planning scaffold (${template.terms.length} sections, ${template.creditMin || 12}-${template.creditMax || 16} credits per term) and apply what I tell you about the student.`;
      autoGrow();
    }
  }

  one("[data-fw-template-clear]")?.addEventListener("click", () => {
    try { sessionStorage.removeItem(TEMPLATE_KEY); } catch { /* storage unavailable */ }
    input.value = "";
    autoGrow();
    renderTemplateBanner();
  });

  // ---- chat ----
  // The box grows with what is typed, up to about six lines, then scrolls.
  const INPUT_MAX_PX = 132;
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, INPUT_MAX_PX)}px`;
  }
  input.addEventListener("input", autoGrow);

  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  let sending = false;

  async function sendMessage(message, { retry = false } = {}) {
    if (sending) return;
    sending = true;
    const submit = form.querySelector("button[type='submit']");
    if (retry) {
      state.chatMessages.pop(); // the failed attempt's error bubble; the user's message stays
      persist();
      renderMessages();
    } else {
      addMessage("user", message);
      input.value = "";
      autoGrow();
    }
    submit.disabled = true;
    submit.textContent = "Sending…";
    showThinking();
    try {
      const data = await apiRequest(root.dataset.chatUrl, {
        method: "POST",
        body: JSON.stringify({ program_requirement_id: program.requirement_id, message }),
      });
      hideThinking();
      addMessage("assistant", data.reply);
      announce("Cora replied.");
      if (data.draft_plan) {
        state.generatedPlan = data.draft_plan;
        persist();
        renderPlan();
      }
    } catch (error) {
      hideThinking();
      const gone = error.status === 404;
      addMessage("assistant", gone ? "That program is no longer available. Choose another program to continue." : (error.message || "Cora could not complete that request."), true, !gone);
      announce("Cora could not complete that request.");
    } finally {
      hideThinking();
      sending = false;
      submit.disabled = false;
      submit.textContent = "Send";
      input.focus();
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    const message = input.value.trim();
    if (message) sendMessage(message);
  });

  // ---- reset and export ----
  async function resetSession() {
    if (state.chatMessages.length || state.generatedPlan) {
      const ok = await confirmDialog({
        title: "Start a new session?",
        message: "This clears the conversation and the draft plan for the current student. Nothing is saved.",
        confirmLabel: "Start new session",
        danger: true,
      });
      if (!ok) return;
    }
    state = emptyState();
    sessionStore.clear();
    renderMessages();
    renderPlan();
    try { await apiRequest(root.dataset.resetUrl, { method: "POST" }); }
    catch (error) { showToast(error.message || "Could not reset the session.", "error"); }
  }

  async function exportPlan(fileType) {
    if (!state.generatedPlan) {
      showToast("Create a draft plan before exporting it.", "error");
      return;
    }
    const exportButton = document.querySelector("[data-fw-export]");
    const exportLabel = exportButton?.textContent;
    if (exportButton) {
      exportButton.disabled = true;
      exportButton.textContent = "Preparing…";
    }
    try {
      const response = await fetch(root.dataset.exportUrl, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken(), "Content-Type": "application/json" },
        body: JSON.stringify({ format: preferredExportFormat(), file_type: fileType, program_requirement_id: program.requirement_id }),
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = "Export failed.";
        try { detail = (await response.json()).detail || detail; } catch { /* non-JSON error body */ }
        if (response.status === 409) {
          showToast(`${detail}`, "error");
          return;
        }
        throw new Error(detail);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      // Use the server's file name (it includes the student's major); fall back to a plain one.
      const disposition = response.headers.get("Content-Disposition") || "";
      link.download = /filename="?([^";]+)"?/.exec(disposition)?.[1] || `academic-plan.${fileType}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      showToast(error.message || "Export failed.", "error");
    } finally {
      if (exportButton) {
        exportButton.disabled = false;
        exportButton.textContent = exportLabel;
      }
    }
  }

  document.querySelector("[data-fw-reset]")?.addEventListener("click", resetSession);

  // ---- Export menu (Word / PDF) ----
  const exportToggle = document.querySelector("[data-fw-export]");
  const exportMenu = document.getElementById("fw-export-menu");
  const exportItems = exportMenu ? [...exportMenu.querySelectorAll("[role='menuitem']")] : [];

  function setExportMenu(open, focusItem = 0) {
    if (!exportMenu) return;
    exportMenu.hidden = !open;
    exportToggle.setAttribute("aria-expanded", String(open));
    if (open) exportItems[focusItem]?.focus();
  }

  exportToggle?.addEventListener("click", () => setExportMenu(exportMenu.hidden));
  exportToggle?.addEventListener("keydown", event => {
    if (event.key === "ArrowDown") { event.preventDefault(); setExportMenu(true, 0); }
    if (event.key === "ArrowUp") { event.preventDefault(); setExportMenu(true, exportItems.length - 1); }
  });
  exportMenu?.addEventListener("keydown", event => {
    const index = exportItems.indexOf(document.activeElement);
    if (event.key === "ArrowDown") { event.preventDefault(); exportItems[(index + 1) % exportItems.length].focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); exportItems[(index - 1 + exportItems.length) % exportItems.length].focus(); }
    else if (event.key === "Escape") { event.preventDefault(); setExportMenu(false); exportToggle.focus(); }
    else if (event.key === "Tab") setExportMenu(false);
  });
  exportItems.filter(item => item.dataset.fwExportType).forEach(item => item.addEventListener("click", () => {
    setExportMenu(false);
    exportToggle.focus();
    exportPlan(item.dataset.fwExportType);
  }));

  // ---- Header line dialog: one line of the faculty member's own wording printed above exported titles ----
  const exportHeaderUrl = root.dataset.exportHeaderUrl;
  const headerDialog = document.getElementById("fw-header-dialog");
  const headerInput = document.getElementById("fw-header-input");
  const headerPreview = headerDialog?.querySelector("[data-fw-header-preview]");
  const headerCount = headerDialog?.querySelector("[data-fw-header-count]");
  const headerError = headerDialog?.querySelector("[data-fw-header-error]");
  const headerSave = headerDialog?.querySelector("[data-fw-header-save]");

  function updateHeaderPreview() {
    const line = normalizeHeaderLine(headerInput.value);
    headerPreview.textContent = line || "(no header line)";
    headerPreview.classList.toggle("is-empty", !line);
    headerCount.textContent = `${Array.from(line).length} / ${HEADER_MAX_LENGTH}`;
  }

  async function openHeaderDialog() {
    headerError.hidden = true;
    headerInput.value = "";
    updateHeaderPreview();
    headerDialog.showModal();
    headerInput.disabled = true;
    try {
      const data = await apiRequest(exportHeaderUrl);
      headerInput.value = data.export_header_line || "";
    } catch (error) {
      headerError.textContent = "Couldn't load your saved header line. You can still type a new one.";
      headerError.hidden = false;
    }
    headerInput.disabled = false;
    updateHeaderPreview();
    headerInput.focus();
    headerInput.select();
  }

  async function saveHeaderLine() {
    headerSave.disabled = true;
    headerSave.textContent = "Saving…";
    headerError.hidden = true;
    try {
      const data = await apiRequest(exportHeaderUrl, {
        method: "PUT",
        body: JSON.stringify({ export_header_line: normalizeHeaderLine(headerInput.value) }),
      });
      headerDialog.close();
      showToast(data.export_header_line ? "Header line saved." : "Header line cleared.");
    } catch (error) {
      headerError.textContent = error.message || "Couldn't save the header line. Try again.";
      headerError.hidden = false;
    } finally {
      headerSave.disabled = false;
      headerSave.textContent = "Save";
    }
  }

  headerInput?.addEventListener("input", updateHeaderPreview);
  headerSave?.addEventListener("click", saveHeaderLine);
  headerDialog?.querySelector("[data-fw-header-cancel]")?.addEventListener("click", () => headerDialog.close());
  headerDialog?.querySelector("[data-fw-header-clear]")?.addEventListener("click", () => {
    headerInput.value = "";
    updateHeaderPreview();
    headerInput.focus();
  });
  headerInput?.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); saveHeaderLine(); }
  });
  exportMenu?.querySelector("[data-fw-export-header]")?.addEventListener("click", () => {
    setExportMenu(false);
    openHeaderDialog();
  });
  document.addEventListener("click", event => {
    if (exportMenu && !exportMenu.hidden && !event.target.closest("[data-fw-export-menu]")) setExportMenu(false);
  });

  // ---- Expand / collapse the chat (hides Sources and widens Cora) ----
  const studio = root.querySelector(".fw-studio");
  const expandButton = one("[data-fw-expand]");

  function setChatWide(wide, { save = true } = {}) {
    studio.classList.toggle("is-chat-wide", wide);
    expandButton.setAttribute("aria-pressed", String(wide));
    expandButton.setAttribute("aria-label", wide ? "Collapse chat" : "Expand chat");
    expandButton.textContent = wide ? "Collapse" : "Expand";
    if (save) { try { localStorage.setItem(CHAT_WIDE_KEY, wide ? "1" : "0"); } catch { /* preference not saved */ } }
    chat.scrollTop = chat.scrollHeight;
    autoGrow();
  }

  expandButton.addEventListener("click", () => setChatWide(!studio.classList.contains("is-chat-wide")));

  renderMessages();
  renderPlan();
  renderTemplateBanner();
  try { if (localStorage.getItem(CHAT_WIDE_KEY) === "1") setChatWide(true, { save: false }); } catch { /* default layout */ }
  autoGrow();
}
