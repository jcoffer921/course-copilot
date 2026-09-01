import { initNavigation } from "./core/navigation.js";
import { initCourseHeader } from "./core/course_header.js";
import { apiRequest } from "./core/api.js";

initNavigation();

const root = document.querySelector("[data-page-section='course-detail']");
const courseId = root?.dataset.courseId;
const byId = id => document.getElementById(id);

function errorMessage(error) {
  if (error?.data && typeof error.data === "object") {
    if (typeof error.data.detail === "string") return error.data.detail;
    const fieldMessage = Object.values(error.data).flat().find(value => typeof value === "string");
    if (fieldMessage) return fieldMessage;
  }
  return error?.message || "Something went wrong.";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function formatDate(isoDate) {
  if (!isoDate) return "";
  const [, m, d] = isoDate.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}
function formatUploaded(value) { return value ? new Date(value).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : "Existing"; }

function relativeLabel(daysUntil) {
  if (daysUntil === 0) return "Today";
  if (daysUntil === 1) return "Tomorrow";
  if (daysUntil > 1) return `${daysUntil} days`;
  return "Overdue";
}

function setBody(id, lines) {
  const el = byId(id);
  if (!el) return;
  if (typeof lines === "string") { el.textContent = lines; return; }
  el.replaceChildren(...lines.map(line => {
    const p = document.createElement("p");
    p.textContent = line;
    return p;
  }));
}

// Same self-healing pattern as course_header.js/materials.js: this page is
// not exempt from the <x-dc> shell, so one `ui` object + one enforceUi()
// writer + a recurring setInterval survives a cold-load reset of `hidden`
// attributes or a wholesale node swap. `cards` holds the last-fetched
// overview payload; each renderX() is a pure no-op before the first
// successful fetch (data undefined), so one broken section's absence never
// blocks the other 6 cards from rendering.
const ui = { loadingHidden: false, errorHidden: true, errorMessage: "", gridHidden: true };
let cards = {};

function renderPriority() {
  const data = cards.priority;
  const heading = byId("ov-priority-heading");
  const detail = byId("ov-priority-detail");
  const link = byId("ov-priority-link");
  const iconUse = byId("ov-priority-icon")?.querySelector("use");
  if (!data || !heading || !detail || !link) return;
  const setIcon = name => { if (iconUse) iconUse.setAttribute("href", `#ot-icon-${name}`); };
  if (data.error) {
    heading.textContent = "Couldn't load";
    detail.textContent = data.error;
    return;
  }
  if (!data.available) {
    heading.textContent = "Nothing due soon";
    detail.textContent = "";
    setIcon("calendar");
    link.textContent = "View in Calendar";
    link.href = `/calendar/?course=${encodeURIComponent(courseId)}`;
    return;
  }
  if (data.kind === "exam") {
    const exam = data.exam;
    heading.textContent = exam.title;
    detail.textContent = `Exam · ${formatDate(exam.date)} · ${relativeLabel(exam.days_until)}`;
    setIcon("exam");
    link.textContent = "Prepare for exam";
    link.href = `/courses/${encodeURIComponent(courseId)}/exams/${encodeURIComponent(exam.id)}/`;
  } else {
    const deadline = data.deadline;
    heading.textContent = deadline.title;
    detail.textContent = `${formatDate(deadline.date)} · ${deadline.relative_label}`;
    setIcon("calendar");
    link.textContent = "View in Calendar";
    link.href = `/calendar/?course=${encodeURIComponent(courseId)}`;
  }
}

function renderStudy() {
  const data = cards.study;
  const link = byId("ov-study-link");
  if (!data || !link) return;
  if (data.error) { setBody("ov-study-body", data.error); return; }
  if (data.in_progress_session) {
    byId("ov-study-topic").textContent = data.in_progress_session.topic || "Continue your session";
    setBody("ov-study-body", `Continue: ${data.in_progress_session.topic || "your session"}`);
    link.textContent = "Continue studying";
    link.href = `/study/?course=${encodeURIComponent(courseId)}&view=session`;
    return;
  }
  if (data.recommendation) {
    const rec = data.recommendation;
    byId("ov-study-topic").textContent = rec.topic || "Recommended study";
    setBody("ov-study-body", [rec.estimated_minutes ? `${rec.estimated_minutes} min` : "", rec.reason].filter(Boolean));
    link.textContent = "Start studying";
    link.href = rec.suggested_mode === "quiz"
      ? `/courses/${encodeURIComponent(courseId)}/study/quiz/`
      : `/courses/${encodeURIComponent(courseId)}/study/flashcards/due/`;
    return;
  }
  setBody("ov-study-body", "Complete a quiz or study session to begin tracking mastery.");
  link.textContent = "Start studying";
  link.href = `/courses/${encodeURIComponent(courseId)}/study/flashcards/due/`;
}

function renderMaterials() {
  const data = cards.materials;
  if (!data) return;
  if (data.error) { setBody("ov-materials-body", data.error); return; }
  if (!data.available) {
    setBody("ov-materials-body", "No materials yet. Upload a syllabus, notes, or slides to get started.");
    byId("ov-materials-count").textContent = "";
    byId("ov-materials-list").replaceChildren();
    return;
  }
  byId("ov-materials-body").textContent = "";
  byId("ov-materials-count").textContent = `${data.count} material${data.count === 1 ? "" : "s"}${data.needs_review ? ` · ${data.needs_review} needs review` : ""}`;
  byId("ov-materials-list").replaceChildren(...(data.recent || []).map(material => {
    const row = document.createElement("div"); row.className = "overview-material-row";
    const icon = document.createElement("span"); icon.className = `overview-file-icon ${material.material_type}`; icon.textContent = material.material_type === "slides" ? "P" : material.original_filename?.toLowerCase().endsWith(".pdf") ? "PDF" : "▤";
    const name = document.createElement("span"); name.textContent = material.original_filename;
    const date = document.createElement("time"); date.textContent = formatUploaded(material.uploaded_at);
    row.append(icon, name, date); return row;
  }));
}

function renderMastery() {
  const data = cards.mastery;
  const fill = byId("ov-mastery-fill");
  const progress = byId("ov-mastery-progress");
  if (!data) return;
  if (data.error) {
    setBody("ov-mastery-body", data.error);
    if (fill) fill.style.width = "0%";
    if (progress) progress.setAttribute("aria-valuenow", "0");
    return;
  }
  if (!data.available) {
    setBody("ov-mastery-body", "Not enough activity to calculate mastery. Complete a quiz or study session to begin.");
    if (fill) fill.style.width = "0%";
    if (progress) progress.setAttribute("aria-valuenow", "0");
    return;
  }
  if (fill) fill.style.width = `${data.score}%`;
  byId("ov-mastery-score").textContent = `${data.score}%`;
  if (progress) progress.setAttribute("aria-valuenow", String(data.score));
  const lines = [];
  if (data.strongest_topic) lines.push(`Strongest: ${data.strongest_topic.topic} — ${Math.round(data.strongest_topic.score * 100)}%`);
  if (data.weakest_topic && data.weakest_topic.topic !== data.strongest_topic?.topic) {
    lines.push(`Needs attention: ${data.weakest_topic.topic} — ${Math.round(data.weakest_topic.score * 100)}%`);
  }
  setBody("ov-mastery-body", lines);
}

function renderGrades() {
  const data = cards.grades;
  if (!data) return;
  if (data.error) { setBody("ov-grades-body", data.error); return; }
  if (!data.available) {
    setBody("ov-grades-body", "No grades entered yet. Add grades to track your progress.");
    return;
  }
  const body = byId("ov-grades-body"); body.replaceChildren();
  const score = document.createElement("strong"); score.className = "overview-grade-score"; score.textContent = `${data.overall_pct}%`;
  const count = document.createElement("span"); count.textContent = `${data.item_count} graded item${data.item_count === 1 ? "" : "s"}`; body.append(score, count);
}

function renderSchedule() {
  const data = cards.schedule;
  const empty = byId("ov-schedule-empty");
  const list = byId("ov-schedule-list");
  if (!data || !empty || !list) return;
  if (data.error) {
    empty.hidden = false;
    empty.textContent = data.error;
    list.hidden = true;
    return;
  }
  if (!data.available) {
    empty.hidden = false;
    empty.textContent = "No upcoming events. Add an event or review your syllabus.";
    list.hidden = true;
    return;
  }
  empty.hidden = true;
  list.hidden = false;
  list.replaceChildren(...data.events.map(event => {
    const li = document.createElement("li");
    li.className = "course-overview-list-row";
    const title = document.createElement("span");
    title.textContent = event.title;
    const when = document.createElement("span");
    when.className = "course-overview-list-meta";
    when.textContent = formatDate(event.date);
    li.append(title, when);
    return li;
  }));
}

function renderCora() {
  const data = cards.cora;
  if (!data) return;
  const link = byId("ov-cora-body");
  if (data.error) { link.textContent = data.error; return; }
  if (!data.available) {
    link.textContent = "Ask Cora ›";
    return;
  }
  link.textContent = `Continue: ${data.session.title} ›`;
}

function enforceUi() {
  const set = (id, hidden) => { const el = byId(id); if (el) el.hidden = hidden; };
  set("course-overview-loading", ui.loadingHidden);
  set("course-overview-error", ui.errorHidden);
  set("course-overview-grid", ui.gridHidden);
  const error = byId("course-overview-error");
  if (error) { const p = error.querySelector("p"); if (p) p.textContent = ui.errorMessage; }
  renderPriority();
  renderStudy();
  renderMaterials();
  renderMastery();
  renderGrades();
  renderSchedule();
  renderCora();
}

async function load({ quiet = false } = {}) {
  if (!quiet) {
    ui.loadingHidden = false;
    ui.errorHidden = true;
    ui.gridHidden = true;
    enforceUi();
  }
  try {
    cards = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/overview/`);
    ui.loadingHidden = true;
    ui.gridHidden = false;
  } catch (error) {
    ui.loadingHidden = true;
    ui.errorHidden = false;
    ui.errorMessage = errorMessage(error);
  }
  enforceUi();
}

if (root && courseId) {
  enforceUi();
  // Delegated (not direct) so the retry button keeps working even if the
  // <x-dc> shell swaps out this static subtree after load.
  document.addEventListener("click", event => {
    if (event.target.closest("#course-overview-error button")) load();
  });
  document.addEventListener("submit", event => {
    if (event.target.id !== "ov-cora-form") return;
    event.preventDefault(); const question = byId("ov-cora-input").value.trim();
    if (question) window.location.assign(`/cora/?course=${encodeURIComponent(courseId)}&q=${encodeURIComponent(question)}`);
  });
  initCourseHeader(courseId);
  load();
  // Proven-necessary cold-load-race mitigation (see materials.js) for this
  // page's dynamically-rendered card grid.
}
