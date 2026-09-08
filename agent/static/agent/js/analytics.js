import { apiRequest } from "./core/api.js";

const root = document.querySelector(".analytics-page");
const $ = (selector) => root.querySelector(selector);
const state = { range: new URLSearchParams(location.search).get("range") || "7d" };

function percent(value, total) {
  return total ? `${Math.round(value / total * 1000) / 10}%` : "0%";
}

function renderTimeline(rows) {
  const el = $("#active-chart");
  if (!rows.length) {
    el.innerHTML = '<p class="analytics-empty">No qualifying activity yet.</p>';
    return;
  }
  const width = 700, height = 210, pad = 30;
  const max = Math.max(1, ...rows.map((row) => row.count));
  const points = rows.map((row, index) => {
    const x = pad + index * ((width - pad * 2) / Math.max(1, rows.length - 1));
    const y = height - pad - (row.count / max) * (height - pad * 2);
    return { x, y, ...row };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const dots = points.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${point.date}: ${point.count} active</title></circle>`).join("");
  const labels = points.filter((_, i) => rows.length <= 10 || i % Math.ceil(rows.length / 7) === 0 || i === rows.length - 1)
    .map((point) => `<text x="${point.x}" y="${height - 5}" text-anchor="middle">${new Date(point.date + "T00:00:00").toLocaleDateString(undefined, {month:"short", day:"numeric"})}</text>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Active students over time"><line x1="${pad}" x2="${width-pad}" y1="${height-pad}" y2="${height-pad}" class="chart-axis"/><polyline points="${line}" class="chart-line"/>${dots}${labels}</svg>`;
}

function renderEngagement(engagement) {
  const labels = {study_sessions:"Study Sessions", quizzes:"Quizzes", flashcards:"Flashcards", cora:"Cora", calendar:"Calendar"};
  const colors = {study_sessions:"#4b8b43", quizzes:"#df672d", flashcards:"#7660b6", cora:"#397daf", calendar:"#e5a913"};
  const entries = Object.entries(engagement).filter(([, value]) => value > 0);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  $("#engagement-total").textContent = `${total} events`;
  $("#engagement-chart").innerHTML = entries.length ? entries.map(([key, value]) => `<div><span>${labels[key]}</span><i><i style="width:${value/max*100}%;background:${colors[key]}"></i></i><strong>${value} <small>(${percent(value,total)})</small></strong></div>`).join("") : '<p class="analytics-empty">No measurable feature engagement in this period.</p>';
}

function renderCourses(rows, total) {
  $("#courses-empty").hidden = rows.length > 0;
  $("#course-rows").innerHTML = rows.map((row) => `<tr><td><strong>${escapeHtml(row.course_id.toUpperCase())}</strong><span>${escapeHtml(row.name)}</span></td><td>${row.students_active} of ${total}</td><td>${row.study_sessions}</td><td>${row.questions_answered}</td><td>${row.first_attempt_accuracy === null ? "Not enough data" : row.first_attempt_accuracy + "%"}</td><td>${row.calendar_connected} of ${row.students_active}</td></tr>`).join("");
}

function escapeHtml(value) {
  const el = document.createElement("span");
  el.textContent = String(value);
  return el.innerHTML;
}

function render(data) {
  const total = data.access_status.total;
  $("#analytics-student-count").textContent = `${total} students`;
  for (const key of ["pending", "active", "suspended"]) {
    $(`#status-${key}`).textContent = data.access_status[key];
    $(`#status-${key}-percent`).textContent = percent(data.access_status[key], total);
  }
  $("#metric-active").textContent = data.metrics.active_students;
  $("#metric-active-detail").textContent = `of ${total} total`;
  $("#metric-sessions").textContent = data.metrics.study_sessions;
  $("#metric-sessions-detail").textContent = `~${data.metrics.active_students ? (data.metrics.study_sessions / data.metrics.active_students).toFixed(1) : "0"} per active student`;
  $("#metric-questions").textContent = data.metrics.questions_answered;
  $("#metric-questions-detail").textContent = `~${data.metrics.active_students ? (data.metrics.questions_answered / data.metrics.active_students).toFixed(1) : "0"} per active student`;
  $("#metric-calendar").textContent = data.metrics.calendar_connected;
  $("#metric-calendar-detail").textContent = `of ${total} students`;
  $("#metric-llm").textContent = data.metrics.llm_requests.toLocaleString();
  renderTimeline(data.timeline);
  renderEngagement(data.engagement);
  renderCourses(data.courses, total);
  $("#impact-resurfacing").title = data.impact.resurfacing.reason;
  $("#impact-calendar").title = data.impact.calendar_retention.reason;
  $("#impact-syllabus").title = data.impact.syllabus_corrections.reason;
}

async function load() {
  $("#analytics-loading").hidden = false;
  $("#analytics-error").hidden = true;
  $("#analytics-content").hidden = true;
  root.querySelectorAll("[data-range]").forEach((button) => button.classList.toggle("selected", button.dataset.range === state.range));
  $("#analytics-export").href = `${root.dataset.export}?range=${state.range}`;
  try {
    const data = await apiRequest(`${root.dataset.api}?range=${state.range}`);
    render(data);
    $("#analytics-content").hidden = false;
  } catch (error) {
    $("#analytics-error").hidden = false;
  } finally {
    $("#analytics-loading").hidden = true;
  }
}

root.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
  state.range = button.dataset.range;
  history.replaceState({}, "", `${location.pathname}?range=${state.range}`);
  load();
}));
$("#analytics-retry").addEventListener("click", load);
load();
