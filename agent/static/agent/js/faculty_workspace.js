import { apiRequest } from "./core/api.js";
import { getCsrfToken } from "./core/csrf.js";
import { confirmDialog } from "./core/dialogs.js";
import { showToast } from "./core/toast.js";
import { runImportFlow } from "./faculty_import_flow.js";
import { categoryCoverage, courseCategoryMap, planSummary, prerequisiteConflicts } from "./faculty_plan_model.js";

const root = document.getElementById("fw-root");
const program = JSON.parse(document.getElementById("fw-active-program")?.textContent || "null");
const requirements = program?.requirements || null;

const one = selector => root?.querySelector(selector);

const EXPORT_FORMAT_KEY = "ontrack.facultyExportFormat";
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
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
    showToast("Choose an Excel file (.xlsx or .xlsm).", "error");
    return;
  }
  try {
    const confirmed = await runImportFlow({ file, importUrl: root.dataset.importUrl, confirmUrl: root.dataset.confirmUrl });
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

// ---- session store: student-specific state lives in sessionStorage only ----
const SESSION_KEY = root?.dataset.sessionKey || "ontrack.facultySession";
const TEMPLATE_KEY = root?.dataset.templateKey || "ontrack.selectedFacultyTemplate";
const emptyState = () => ({ programId: program?.requirement_id || null, chatMessages: [], generatedPlan: null, dismissed: [] });

const sessionStore = {
  read() {
    try {
      const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      if (value && value.programId === program?.requirement_id) return { ...emptyState(), ...value };
    } catch { /* unreadable storage falls through to a fresh session */ }
    return emptyState();
  },
  write(state) {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(state)); } catch { /* storage unavailable */ }
  },
  clear() {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* storage unavailable */ }
  },
  hasState() {
    try {
      const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      return Boolean(value) && value.programId === program?.requirement_id;
    } catch { return false; }
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

  function renderPlan() {
    const draft = state.generatedPlan;
    planEmpty.hidden = Boolean(draft);
    planBody.hidden = !draft;
    renderCoverage();
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
    for (const message of state.chatMessages) {
      chat.append(el("div", { className: `fw-msg ${message.role === "user" ? "is-user" : "is-assistant"}${message.error ? " is-error" : ""}`, text: message.content }));
    }
    chat.scrollTop = chat.scrollHeight;
  }

  function addMessage(role, content, error = false) {
    state.chatMessages.push({ role, content, ...(error ? { error: true } : {}) });
    persist();
    renderMessages();
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
    }
  }

  one("[data-fw-template-clear]")?.addEventListener("click", () => {
    try { sessionStorage.removeItem(TEMPLATE_KEY); } catch { /* storage unavailable */ }
    input.value = "";
    renderTemplateBanner();
  });

  // ---- chat ----
  root.querySelectorAll("[data-fw-prompt]").forEach(button => button.addEventListener("click", () => {
    input.value = button.dataset.fwPrompt;
    input.focus();
  }));

  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    const submit = form.querySelector("button[type='submit']");
    addMessage("user", message);
    input.value = "";
    submit.disabled = true;
    try {
      const data = await apiRequest(root.dataset.chatUrl, {
        method: "POST",
        body: JSON.stringify({ program_requirement_id: program.requirement_id, message }),
      });
      addMessage("assistant", data.reply);
      if (data.draft_plan) {
        state.generatedPlan = data.draft_plan;
        persist();
        renderPlan();
      }
    } catch (error) {
      const gone = error.status === 404;
      addMessage("assistant", gone ? "That program is no longer available. Choose another program to continue." : (error.message || "Cora could not complete that request."), true);
    } finally {
      submit.disabled = false;
      input.focus();
    }
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

  async function exportPlan() {
    if (!state.generatedPlan) {
      showToast("Create a draft plan before exporting it.", "error");
      return;
    }
    try {
      const response = await fetch(root.dataset.exportUrl, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken(), "Content-Type": "application/json" },
        body: JSON.stringify({ format: preferredExportFormat(), program_requirement_id: program.requirement_id }),
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
      link.download = "academic-plan.docx";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(error.message || "Export failed.", "error");
    }
  }

  document.querySelector("[data-fw-reset]")?.addEventListener("click", resetSession);
  document.querySelector("[data-fw-export]")?.addEventListener("click", exportPlan);

  renderMessages();
  renderPlan();
  renderTemplateBanner();
}
