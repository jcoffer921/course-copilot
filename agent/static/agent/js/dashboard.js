import { initNavigation } from "./core/navigation.js";
import { apiRequest } from "./core/api.js";
import { showToast } from "./core/toast.js";

initNavigation();
const byId = id => document.getElementById(id);
const root = document.querySelector("[data-page-section='dashboard']");
const routes = { calendar: root?.dataset.calendarUrl || "/calendar/", courses: root?.dataset.coursesUrl || "/courses/", cora: root?.dataset.coraUrl || "/cora/", study: root?.dataset.studyUrl || "/study/" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DASHBOARD_COURSE_LIMIT = 3;
const DASHBOARD_DEADLINE_LIMIT = 3;
const state = { currentRecommendation: null };
const ui = { loadingHidden: false, errorHidden: true, contentHidden: true, alertHidden: true, alertText: "", alertIsError: false, recommendationBadgeHidden: true, recommendationEmptyHidden: true, recommendationActionsHidden: true, recommendationFactsHidden: true, planEmptyHidden: true, coursesEmptyHidden: true, deadlinesEmptyHidden: true };

function errorMessage(error) {
  if (error?.data && typeof error.data === "object") {
    const value = Object.values(error.data).flat().find(item => typeof item === "string");
    if (value) return value;
  }
  return error?.message || "Something went wrong.";
}

function formatDateShort(isoDate) { const [, month, day] = isoDate.split("-").map(Number); return `${MONTHS[month - 1]} ${day}`; }
function daysUntilLabel(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  const target = new Date(year, month - 1, day); const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((target - today) / 86400000);
  if (days < 0) return `${Math.abs(days)} day${days === -1 ? "" : "s"} ago`;
  if (days === 0) return "Today"; if (days === 1) return "Tomorrow"; return `${days} days`;
}
function courseInitials(courseId, name) {
  const words = String(name || courseId || "").trim().split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : String(courseId || "").slice(0, 2)).toUpperCase();
}
function updateGreeting() {
  const timezone = root?.dataset.timezone || "America/New_York";
  const firstName = root?.dataset.firstName || "there";
  let hour;
  try {
    const hourPart = new Intl.DateTimeFormat("en-US", { timeZone: timezone, hour: "numeric", hourCycle: "h23" })
      .formatToParts(new Date()).find(part => part.type === "hour");
    hour = Number(hourPart?.value);
  } catch {
    hour = new Date().getHours();
  }
  const period = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  byId("dash-greeting").textContent = `${period}, ${firstName}`;
}
function svgIcon(name, className = "ot-icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className); svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use"); use.setAttribute("href", `#ot-icon-${name}`); svg.append(use); return svg;
}

function enforceUi() {
  const set = (id, hidden) => { const el = byId(id); if (el) el.hidden = hidden; };
  set("dash-loading", ui.loadingHidden); set("dash-error", ui.errorHidden); set("dash-content", ui.contentHidden);
  set("dash-recommendation-badge", ui.recommendationBadgeHidden); set("dash-recommendation-empty", ui.recommendationEmptyHidden);
  set("dash-recommendation-actions", ui.recommendationActionsHidden); set("dash-recommendation-facts", ui.recommendationFactsHidden);
  set("dash-plan-empty", ui.planEmptyHidden); set("dash-courses-empty", ui.coursesEmptyHidden); set("dash-deadlines-empty", ui.deadlinesEmptyHidden);
  const alert = byId("dash-alert"); if (alert) { alert.hidden = ui.alertHidden; alert.textContent = ui.alertText; alert.classList.toggle("error", ui.alertIsError); }
}
function showAlert(message, isError = false) { ui.alertHidden = false; ui.alertText = message; ui.alertIsError = isError; enforceUi(); }

function renderStatCard(prefix, item, emptyLabel) {
  const link = byId(`dash-${prefix}-link`); const course = byId(`dash-${prefix}-course`); const when = byId(`dash-${prefix}-when`);
  if (!item) { link.textContent = emptyLabel; link.href = routes.calendar; course.hidden = true; when.textContent = ""; return; }
  link.textContent = item.title; link.href = routes.calendar;
  if (item.course_id) { course.hidden = false; course.textContent = item.course_name || item.course_id.toUpperCase(); course.style.color = item.course_color || "inherit"; } else course.hidden = true;
  when.textContent = `${formatDateShort(item.date)} · ${daysUntilLabel(item.date)}`;
}
function renderStreak(data) {
  byId("dash-streak-title").textContent = `${data.streak} day${data.streak === 1 ? "" : "s"}`;
  byId("dash-streak-sub").textContent = data.streak ? "Keep it going!" : "Start today";
  byId("dash-streak-week").replaceChildren(...data.streak_week.map(day => {
    const dot = document.createElement("span"); dot.className = `dash-streak-dot${day.active ? " dash-streak-dot-active" : day.is_future ? " dash-streak-dot-future" : ""}`;
    dot.textContent = day.label; dot.title = `${day.date}${day.active ? ", studied" : ""}`; return dot;
  }));
}
function renderPlan(data) {
  const items = data.today_plan || []; ui.planEmptyHidden = !!items.length;
  byId("dash-plan-list").replaceChildren(...items.map(item => {
    const li = document.createElement("li"); li.className = "dash-plan-item";
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.setAttribute("aria-label", `Mark ${item.title} complete`); checkbox.addEventListener("change", () => completePlanItem(item, checkbox));
    const body = document.createElement("div"); body.className = "dash-plan-item-body";
    const title = document.createElement("div"); title.className = "dash-plan-item-title"; title.textContent = item.title;
    const meta = document.createElement("div"); meta.className = "dash-plan-item-meta";
    const tag = document.createElement("span"); const course = data.courses?.[item.course_id]; tag.style.color = course?.course_color || "inherit"; tag.textContent = course?.course_name || item.course_id?.toUpperCase() || "";
    meta.append(tag, document.createTextNode(` · ${item.detail}`)); body.append(title, meta);
    const effort = document.createElement("span"); effort.className = "dash-plan-item-effort"; effort.append(svgIcon("clock"), document.createTextNode(`${item.effort_minutes} min`));
    li.append(checkbox, body, effort); return li;
  }));
}
async function completePlanItem(item, checkbox) {
  checkbox.disabled = true;
  try {
    if (item.kind === "deadline") await apiRequest(`/api/deadlines/${encodeURIComponent(item.id)}/`, { method: "PATCH", body: JSON.stringify({ completed: true }) });
    else await apiRequest("/api/recommendations/dismiss/", { method: "POST", body: JSON.stringify({ course_id: item.course_id, topic: item.topic }) });
    showToast("Nice work!"); await loadDashboard({ quiet: true });
  } catch (error) { checkbox.checked = false; checkbox.disabled = false; showAlert(errorMessage(error), true); }
}
function renderRecommendation(rec) {
  const has = !!rec; ui.recommendationEmptyHidden = has; ui.recommendationBadgeHidden = !has; ui.recommendationActionsHidden = !has; ui.recommendationFactsHidden = true;
  byId("dash-recommendation-title").hidden = !has; byId("dash-recommendation-reason").hidden = !has; state.currentRecommendation = rec;
  const evidence = byId("dash-recommendation-evidence");
  const sourceList = byId("dash-recommendation-sources");
  sourceList.replaceChildren(); evidence.hidden = !has;
  if (!has) return enforceUi();
  byId("dash-recommendation-title").textContent = `Review ${rec.topic}`; byId("dash-recommendation-reason").textContent = rec.reason;
  sourceList.replaceChildren(...(rec.sources || []).map(source => {
    const link = document.createElement("a"); link.className = "recommendation-source"; link.href = source.download_url;
    const badge = document.createElement("span"); badge.className = "recommendation-file-type"; badge.textContent = source.file_type;
    const copy = document.createElement("span"); copy.className = "recommendation-source-copy";
    const name = document.createElement("strong"); name.textContent = source.filename;
    const excerpt = document.createElement("span"); excerpt.textContent = `${source.page ? `Page ${source.page} · ` : ""}${source.excerpt}`;
    copy.append(name, excerpt); link.append(badge, copy); return link;
  }));
  byId("dash-recommendation-start").href = `${routes.study}?view=session&course=${encodeURIComponent(rec.course_id)}&topic=${encodeURIComponent(rec.topic)}`;
  const sourceCount = (rec.sources || []).length;
  byId("dash-recommendation-facts").textContent = `${sourceCount} supporting course file${sourceCount === 1 ? "" : "s"} · Mastery gap ${Math.round(rec.gap * 100)}% · Deadline urgency ${Math.round(rec.urgency * 100)}% · Importance ${Math.round(rec.importance * 100)}% · Recency ${Math.round(rec.recency * 100)}%`;
  enforceUi();
}
function renderCourses(data) {
  const entries = Object.entries(data.courses || {}).filter(([, item]) => !item.error); ui.coursesEmptyHidden = !!(entries.length || data.drafts?.length);
  byId("dash-courses-grid").replaceChildren(...entries.slice(0, DASHBOARD_COURSE_LIMIT).map(([courseId, summary]) => {
    const card = document.createElement("article"); card.className = "dash-course-card";
    const main = document.createElement("a"); main.className = "dash-course-main"; main.href = `/courses/${encodeURIComponent(courseId)}/materials/`;
    const head = document.createElement("div"); head.className = "dash-course-head";
    const badge = document.createElement("span"); badge.className = "dash-course-badge"; badge.style.background = summary.course_color; badge.textContent = courseInitials(courseId, summary.course_name);
    const name = document.createElement("h3"); name.textContent = summary.course_name || courseId; head.append(badge, name);
    const nextLabel = document.createElement("p"); nextLabel.className = "dash-course-next-label"; nextLabel.textContent = "Next deadline";
    const deadline = document.createElement("p"); deadline.className = "dash-course-deadline"; deadline.textContent = summary.next_deadline ? `${summary.next_deadline.title}\n${formatDateShort(summary.next_deadline.date)} · ${daysUntilLabel(summary.next_deadline.date)}` : "No upcoming deadline";
    const masteryLabel = document.createElement("p"); masteryLabel.className = "dash-course-next-label"; masteryLabel.textContent = "Mastery";
    const row = document.createElement("div"); row.className = "dash-course-mastery"; const track = document.createElement("div"); track.className = "dash-course-mastery-track"; track.setAttribute("role", "progressbar"); track.setAttribute("aria-label", `${summary.course_name} mastery`); track.setAttribute("aria-valuemin", "0"); track.setAttribute("aria-valuemax", "100");
    const fill = document.createElement("div"); fill.className = "dash-course-mastery-fill"; fill.style.width = `${summary.mastery_pct ?? 0}%`; fill.style.background = summary.course_color; track.append(fill);
    const value = document.createElement("span"); value.textContent = summary.mastery_pct == null ? "Not enough data" : `${summary.mastery_pct}%`; if (summary.mastery_pct != null) track.setAttribute("aria-valuenow", String(summary.mastery_pct)); row.append(track, value);
    main.append(head, nextLabel, deadline, masteryLabel, row);
    const menu = document.createElement("details"); menu.className = "dash-course-menu";
    const menuToggle = document.createElement("summary"); menuToggle.setAttribute("aria-label", `Actions for ${summary.course_name}`); menuToggle.textContent = "⋮";
    const menuBody = document.createElement("div"); const open = document.createElement("a"); open.href = main.href; open.textContent = "Open course"; menuBody.append(open); menu.append(menuToggle, menuBody);
    card.append(main, menu); return card;
  }));
}
function renderDeadlines(data) {
  const items = (data.deadlines || []).slice(0, DASHBOARD_DEADLINE_LIMIT); ui.deadlinesEmptyHidden = !!items.length;
  byId("dash-deadlines-list").replaceChildren(...items.map(item => {
    const row = document.createElement("a"); row.className = "dash-deadline-row"; row.href = routes.calendar;
    const icon = document.createElement("span"); icon.className = "dash-deadline-icon"; icon.style.setProperty("--course-color", item.course_color || "#557c48"); icon.append(svgIcon("calendar"));
    const body = document.createElement("div"); const title = document.createElement("div"); title.className = "dash-plan-item-title"; title.textContent = item.title;
    const course = document.createElement("div"); course.className = "material-meta"; course.style.color = item.course_color || "inherit"; course.textContent = item.course_name || item.course_id?.toUpperCase() || "General"; body.append(title, course);
    const when = document.createElement("div"); when.className = "dash-deadline-when";
    const dateLine = document.createElement("div"); dateLine.textContent = formatDateShort(item.date);
    const relativeLine = document.createElement("div"); relativeLine.className = "material-meta"; relativeLine.textContent = daysUntilLabel(item.date);
    when.append(dateLine, relativeLine); row.append(icon, body, when); return row;
  }));
}
async function loadDashboard({ quiet = false } = {}) {
  if (!quiet) { ui.loadingHidden = false; ui.errorHidden = true; ui.contentHidden = true; enforceUi(); }
  try {
    const data = await apiRequest("/api/dashboard/"); renderStatCard("next-deadline", data.next_deadline, "Nothing due soon"); renderStatCard("next-exam", data.next_exam, "No exam scheduled"); renderStreak(data); renderPlan(data); renderRecommendation(data.recommendation); renderCourses(data); renderDeadlines(data);
    if (data.warnings?.length) showAlert(`${data.warnings.length} course${data.warnings.length === 1 ? "" : "s"} could not be included. Your other dashboard data is still available.`, true);
    ui.loadingHidden = true; ui.contentHidden = false;
  } catch (error) { ui.loadingHidden = true; ui.errorHidden = false; byId("dash-error").querySelector("p").textContent = errorMessage(error); }
  enforceUi();
}
async function dismissRecommendation() { if (!state.currentRecommendation) return; try { await apiRequest("/api/recommendations/dismiss/", { method: "POST", body: JSON.stringify({ course_id: state.currentRecommendation.course_id, topic: state.currentRecommendation.topic }) }); await loadDashboard({ quiet: true }); } catch (error) { showAlert(errorMessage(error), true); } }

function bind() {
  document.addEventListener("click", event => {
    const target = event.target; if (target.closest("#dash-retry")) return loadDashboard();
    if (target.closest("#dash-recommendation-why")) { ui.recommendationFactsHidden = !ui.recommendationFactsHidden; target.closest("#dash-recommendation-why").setAttribute("aria-expanded", String(!ui.recommendationFactsHidden)); return enforceUi(); }
    if (target.closest("#dash-recommendation-dismiss")) return dismissRecommendation();
  });
  document.addEventListener("submit", event => { if (event.target.id !== "dash-cora-form") return; event.preventDefault(); const question = byId("dash-cora-input").value.trim(); if (question) window.location.assign(`${routes.cora}?q=${encodeURIComponent(question)}`); });
}

if (root) { bind(); updateGreeting(); loadDashboard(); window.setInterval(enforceUi, 400); window.setInterval(updateGreeting, 60_000); [900, 1800].forEach(delay => window.setTimeout(() => loadDashboard({ quiet: true }), delay)); }
