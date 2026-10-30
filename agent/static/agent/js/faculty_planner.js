import { apiRequest } from "./core/api.js";
import { getCsrfToken } from "./core/csrf.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();

const root = document.querySelector(".faculty-cora-page");
const byId = id => document.getElementById(id);
const one = selector => root?.querySelector(selector);
const all = selector => [...(root?.querySelectorAll(selector) || [])];
const programs = JSON.parse(byId("faculty-program-requirements")?.textContent || "[]");
const selectedProgram = programs[0] || null;
const storageKey = root?.dataset.sessionStorageKey || "ontrack.facultySession";
const selectedTemplateKey = "ontrack.selectedFacultyTemplate";
const emptySession = () => ({ activeFile: null, detectedColumns: [], majors: [], rowCount: 0, chatMessages: [], generatedPlan: null });

function readSession() {
  try { return { ...emptySession(), ...JSON.parse(sessionStorage.getItem(storageKey) || "{}") }; }
  catch { return emptySession(); }
}

let facultySession = readSession();
let activePlanTab = "plan";

function readSelectedTemplate() {
  try {
    const template = JSON.parse(sessionStorage.getItem(selectedTemplateKey) || "null");
    return template && typeof template.name === "string" && Array.isArray(template.terms) ? template : null;
  } catch { return null; }
}

function renderSelectedTemplate() {
  const template = readSelectedTemplate();
  const banner = byId("faculty-template-selection");
  banner.hidden = !template;
  if (!template) return;
  setText("[data-selected-template-name]", `${template.name} selected`);
  const input = byId("faculty-chat-input");
  if (!input.value) {
    const creditRange = `${template.creditMin || 12}–${template.creditMax || 16} credits`;
    input.value = `Use the ${template.name} as the planning scaffold (${template.terms.length} sections, ${creditRange}) and apply the active session context.`;
  }
}

function writeSession() {
  sessionStorage.setItem(storageKey, JSON.stringify(facultySession));
}

function setText(selector, value) {
  const node = one(selector);
  if (node) node.textContent = value;
}

function showAlert(message, isError = false) {
  const alert = byId("faculty-cora-alert");
  alert.textContent = message;
  alert.classList.toggle("error", isError);
  alert.hidden = false;
  window.setTimeout(() => { alert.hidden = true; }, 5000);
}

function errorMessage(error) {
  return error?.data?.detail || error?.message || "Cora could not complete that request.";
}

function icon(symbol) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ot-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${symbol}`);
  svg.append(use);
  return svg;
}

function renderSession() {
  const hasFile = Boolean(facultySession.activeFile);
  all("[data-empty-state]").forEach(node => { node.hidden = hasFile; });
  all("[data-active-state]").forEach(node => { node.hidden = !hasFile; });
  const badge = one("[data-file-badge]");
  badge.textContent = hasFile ? "1 file active" : "No active file";
  badge.classList.toggle("is-active", hasFile);
  if (hasFile) {
    const uploaded = facultySession.activeFile.uploadedAt ? new Date(facultySession.activeFile.uploadedAt) : null;
    setText("[data-session-filename]", facultySession.activeFile.name || "Temporary advising file");
    setText("[data-session-uploaded]", uploaded && !Number.isNaN(uploaded.valueOf()) ? `Uploaded ${uploaded.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "Available for this session");
  }
  const columns = Array.isArray(facultySession.detectedColumns) ? facultySession.detectedColumns : [];
  const majors = Array.isArray(facultySession.majors) ? facultySession.majors : [];
  setText("[data-majors-copy]", hasFile ? (majors.join(", ") || "No major column detected") : "Will appear after upload");
  setText("[data-students-copy]", hasFile ? `${facultySession.rowCount || 0} rows` : "Will appear after upload");
  setText("[data-columns-copy]", hasFile ? (columns.slice(0, 4).join(", ") || "No columns detected") : "Will appear after upload");
  setText("[data-majors-count]", hasFile ? majors.length : "—");
  setText("[data-student-count]", hasFile ? facultySession.rowCount || 0 : "—");
  setText("[data-column-count]", hasFile ? columns.length : "—");
  setText("[data-insight-students]", hasFile ? facultySession.rowCount || 0 : 0);
  setText("[data-insight-majors]", hasFile ? majors.length : 0);
  setText("[data-insight-columns]", hasFile ? columns.length : 0);
}

function appendMessage(role, content, persist = true) {
  const messages = byId("faculty-chat-messages");
  byId("faculty-chat-empty").hidden = true;
  messages.hidden = false;
  const message = document.createElement("article");
  message.className = `faculty-chat-message faculty-chat-message-${role}`;
  const avatar = document.createElement("span");
  avatar.className = "faculty-chat-avatar";
  if (role === "assistant") avatar.append(icon("ot-icon-sparkle"));
  else avatar.textContent = (window.CURRENT_USER_NAME || "You").split(/\s+/).map(part => part[0]).join("").slice(0, 2).toUpperCase();
  const copy = document.createElement("p");
  copy.textContent = content;
  message.append(avatar, copy);
  messages.append(message);
  messages.scrollTop = messages.scrollHeight;
  if (persist) {
    facultySession.chatMessages.push({ role, content });
    writeSession();
  }
}

function renderMessages() {
  byId("faculty-chat-messages").replaceChildren();
  if (!facultySession.chatMessages.length) {
    byId("faculty-chat-empty").hidden = false;
    byId("faculty-chat-messages").hidden = true;
    return;
  }
  facultySession.chatMessages.forEach(message => appendMessage(message.role, message.content, false));
}

function courseCategory(code) {
  for (const category of selectedProgram?.requirements?.categories || []) {
    if ((category.courses || []).some(course => course.code === code)) return category.name || "Major";
  }
  return "Elective";
}

function renderPlanView(container, draft) {
  (draft.semesters || []).forEach((semester, index) => {
    const section = document.createElement("section");
    section.className = "faculty-plan-semester";
    const header = document.createElement("header");
    const number = document.createElement("b"); number.textContent = index + 1;
    const label = document.createElement("strong"); label.textContent = semester.label || "Semester";
    const total = document.createElement("span");
    total.textContent = `${(semester.courses || []).reduce((sum, course) => sum + Number(course.credits || 0), 0)} credits`;
    header.append(number, label, total);
    const list = document.createElement("ul");
    (semester.courses || []).forEach(course => {
      const item = document.createElement("li");
      const title = document.createElement("span"); title.textContent = [course.code, course.title].filter(Boolean).join(" — ");
      const pill = document.createElement("span"); pill.className = "faculty-course-pill"; pill.textContent = course.category || courseCategory(course.code);
      const credits = document.createElement("small"); credits.textContent = `${course.credits || 0} cr`;
      item.append(title, pill, credits); list.append(item);
    });
    section.append(header, list); container.append(section);
  });
}

function renderRequirements(container) {
  if (!selectedProgram) {
    container.innerHTML = '<p class="faculty-plan-text">No confirmed curriculum is available yet. Add program requirements before generating a grounded plan.</p>';
    return;
  }
  const heading = document.createElement("h3"); heading.className = "faculty-plan-text"; heading.textContent = `${selectedProgram.program_name} · ${selectedProgram.catalog_year}`; container.append(heading);
  (selectedProgram.requirements?.categories || []).forEach(category => {
    const section = document.createElement("section"); section.className = "faculty-plan-semester";
    const header = document.createElement("header");
    const label = document.createElement("strong"); label.textContent = category.name;
    const credits = document.createElement("span"); credits.textContent = `${category.credits_required || 0} credits`;
    header.append(label, credits);
    const list = document.createElement("ul");
    (category.courses || []).forEach(course => { const item = document.createElement("li"); item.textContent = `${course.code} — ${course.title}`; list.append(item); });
    section.append(header, list); container.append(section);
  });
}

function renderPlan() {
  const draft = facultySession.generatedPlan;
  byId("faculty-plan-empty").hidden = Boolean(draft);
  byId("faculty-plan-content").hidden = !draft;
  byId("faculty-plan-actions").hidden = !draft;
  one("[data-plan-badge]").hidden = !draft || !facultySession.activeFile;
  setText("#faculty-plan-subtitle", draft?.student_major || "");
  if (!draft) return;
  const content = byId("faculty-plan-content"); content.replaceChildren();
  if (activePlanTab === "requirements") renderRequirements(content);
  else if (activePlanTab === "notes") {
    const notes = document.createElement("p"); notes.className = "faculty-plan-text"; notes.textContent = draft.notes || "No additional notes for this plan."; content.append(notes);
  } else renderPlanView(content, draft);
}

async function clearChat() {
  facultySession.chatMessages = [];
  facultySession.generatedPlan = null;
  writeSession(); renderMessages(); renderPlan();
  try { await apiRequest(root.dataset.resetUrl, { method: "POST" }); }
  catch (error) { showAlert(errorMessage(error), true); }
}

async function clearSession() {
  facultySession = emptySession();
  sessionStorage.removeItem(storageKey);
  renderSession(); renderMessages(); renderPlan();
  try { await apiRequest(root.dataset.resetUrl, { method: "POST" }); }
  catch (error) { showAlert(errorMessage(error), true); }
}

all("[data-prompt]").forEach(button => button.addEventListener("click", () => {
  byId("faculty-chat-input").value = button.dataset.prompt;
  byId("faculty-chat-input").focus();
}));

all("[data-workflow]").forEach(button => button.addEventListener("click", () => {
  if (button.hasAttribute("data-requires-file") && !facultySession.activeFile) {
    showAlert("Upload an advising file before using student-specific analysis.", true);
    return;
  }
  byId("faculty-chat-input").value = button.dataset.workflow;
  byId("faculty-chat-input").focus();
}));

all("[data-plan-tab]").forEach(button => button.addEventListener("click", () => {
  activePlanTab = button.dataset.planTab;
  all("[data-plan-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab === button)));
  renderPlan();
}));

one("[data-remove-file]")?.addEventListener("click", () => {
  facultySession.activeFile = null; facultySession.detectedColumns = []; facultySession.majors = []; facultySession.rowCount = 0; facultySession.generatedPlan = null;
  writeSession(); renderSession(); renderPlan();
});
one("[data-clear-chat]")?.addEventListener("click", clearChat);
one("[data-clear-session]")?.addEventListener("click", clearSession);
one("[data-clear-selected-template]")?.addEventListener("click", () => {
  sessionStorage.removeItem(selectedTemplateKey);
  renderSelectedTemplate();
});

byId("faculty-chat-form")?.addEventListener("submit", async event => {
  event.preventDefault();
  const input = byId("faculty-chat-input");
  const message = input.value.trim();
  if (!message) return;
  appendMessage("user", message); input.value = "";
  if (!selectedProgram) {
    appendMessage("assistant", "I need a confirmed program curriculum before I can give grounded academic guidance. Please add program requirements from the faculty workflow first.");
    return;
  }
  const submit = event.currentTarget.querySelector("button[type='submit']"); submit.disabled = true;
  try {
    const data = await apiRequest(root.dataset.chatUrl, { method: "POST", body: JSON.stringify({ program_requirement_id: selectedProgram.requirement_id, message }) });
    appendMessage("assistant", data.reply);
    if (data.draft_plan) { facultySession.generatedPlan = data.draft_plan; writeSession(); renderPlan(); }
  } catch (error) { appendMessage("assistant", errorMessage(error)); }
  finally { submit.disabled = false; input.focus(); }
});

one("[data-copy-plan]")?.addEventListener("click", async () => {
  const draft = facultySession.generatedPlan;
  if (!draft) return;
  const summary = (draft.semesters || []).map(semester => `${semester.label}: ${(semester.courses || []).map(course => course.code || course.title).join(", ")}`).join("\n");
  await navigator.clipboard.writeText(summary);
  showAlert("Plan summary copied.");
});

one("[data-export-plan]")?.addEventListener("click", async () => {
  try {
    const response = await fetch(root.dataset.exportUrl, { method: "POST", headers: { "X-CSRFToken": getCsrfToken() }, credentials: "same-origin" });
    if (!response.ok) throw new Error("Create a plan before exporting it.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = "academic-plan.docx"; link.click(); URL.revokeObjectURL(url);
  } catch (error) { showAlert(errorMessage(error), true); }
});

renderSession(); renderMessages(); renderPlan(); renderSelectedTemplate();
