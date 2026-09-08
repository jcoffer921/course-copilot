import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";
import { initCourseHeader } from "./core/course_header.js";

initNavigation();
const root = document.querySelector("[data-page-section='course-mastery']");
const courseId = root?.dataset.courseId;
const byId = id => document.getElementById(id);
let rows = [];
let topics = [];

const label = value => String(value).replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
function renderTopics() {
  const filter = byId("mastery-filter").value;
  const scored = new Map(rows.map(row => [row.topic, row]));
  const display = topics.map(topic => scored.get(topic) || { topic, status: "not_started", score: null, attempts: 0, reason: "No qualifying study evidence yet." }).filter(row => filter === "all" || row.status === filter);
  const host = byId("mastery-topic-list");
  host.replaceChildren(...display.map(row => {
    const details = document.createElement("details"); details.className = "mastery-topic-row";
    const pct = row.score == null ? null : Math.round(row.score * 100);
    const summary = document.createElement("summary");
    const topicName = document.createElement("strong"); topicName.textContent = row.topic;
    const status = document.createElement("span"); status.className = `mastery-status ${row.status}`; status.textContent = label(row.status);
    const progress = document.createElement("span"); progress.className = "topic-progress"; progress.setAttribute("role", "progressbar"); progress.setAttribute("aria-label", `${row.topic} mastery`); progress.setAttribute("aria-valuemin", "0"); progress.setAttribute("aria-valuemax", "100"); progress.setAttribute("aria-valuenow", String(pct ?? 0));
    const fill = document.createElement("i"); fill.style.width = `${pct ?? 0}%`; progress.append(fill);
    const score = document.createElement("b"); score.textContent = pct == null ? "—" : `${pct}%`; summary.append(topicName, status, progress, score);
    const explanation = document.createElement("div"); explanation.className = "mastery-topic-detail";
    const reason = document.createElement("p"); reason.textContent = row.reason;
    const attempts = document.createElement("p"); attempts.textContent = `${row.attempts || 0} recorded attempt(s).`;
    const study = document.createElement("a"); study.href = `/courses/${encodeURIComponent(courseId)}/study/?topic=${encodeURIComponent(row.topic)}`; study.textContent = "Study this topic"; explanation.append(reason, attempts, study);
    details.append(summary, explanation); return details;
  }));
  if (!display.length) host.innerHTML = '<p class="learning-empty">No topics match this filter.</p>';
}

function renderSummary(recommendations, sessions) {
  const scored = rows.filter(row => row.score != null);
  const overall = scored.length ? Math.round(scored.reduce((sum, row) => sum + row.score, 0) / scored.length * 100) : null;
  byId("mastery-overall-score").textContent = overall == null ? "—" : `${overall}%`;
  byId("mastery-overall-ring").setAttribute("aria-valuenow", overall == null ? "0" : String(overall));
  byId("mastery-overall-ring").style.setProperty("--progress", `${overall || 0}%`);
  byId("mastery-overall-label").textContent = overall == null ? "Not enough activity yet" : overall >= 70 ? "Proficient" : overall >= 40 ? "Learning" : "Needs review";
  const mastered = rows.filter(row => ["proficient", "exam_ready"].includes(row.status)).length;
  const review = rows.filter(row => ["needs_review", "at_risk", "learning"].includes(row.status)).length;
  byId("mastery-mastered-count").textContent = `${mastered} of ${topics.length}`; byId("mastery-review-count").textContent = `${review} topic${review === 1 ? "" : "s"}`;
  const rec = recommendations.find(item => item.course_id === courseId);
  if (rec) { byId("mastery-rec-topic").textContent = `Focus on ${rec.topic}`; byId("mastery-rec-reason").textContent = rec.reason; byId("mastery-study-link").href = `/courses/${encodeURIComponent(courseId)}/study/?topic=${encodeURIComponent(rec.topic)}`; }
  byId("mastery-scored-topics").textContent = scored.length; byId("mastery-attempts").textContent = rows.reduce((sum, row) => sum + (row.attempts || 0), 0);
  const dates = [...rows.map(row => row.last_seen).filter(Boolean), ...sessions.map(row => row.completed_at || row.started_at).filter(Boolean)].sort();
  byId("mastery-last-activity").textContent = dates.length ? new Date(dates.at(-1)).toLocaleDateString() : "—";
  const evidence = byId("mastery-evidence-list"); evidence.replaceChildren(...rows.filter(row => row.last_seen).slice().sort((a,b) => String(b.last_seen).localeCompare(String(a.last_seen))).slice(0,4).map(row => { const item = document.createElement("div"); item.className = "evidence-row"; const date = document.createElement("time"); date.textContent = new Date(row.last_seen).toLocaleDateString(); const topic = document.createElement("span"); topic.textContent = row.topic; const reason = document.createElement("strong"); reason.textContent = row.reason; item.append(date, topic, reason); return item; }));
  if (!evidence.children.length) evidence.innerHTML = "<p>Complete study activities to build traceable evidence.</p>";
}

async function load() {
  try {
    const [syllabus, mastery, recs, sessions] = await Promise.all([apiRequest(`/api/courses/${encodeURIComponent(courseId)}/syllabus/`).catch(error => error.status === 404 ? {topics:[]} : Promise.reject(error)), apiRequest(`/api/courses/${encodeURIComponent(courseId)}/mastery/`), apiRequest("/api/recommendations/?limit=50"), apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/?limit=20`)]);
    topics = syllabus.topics || []; rows = mastery || []; renderSummary(recs.recommendations || [], sessions.sessions || []); renderTopics();
    byId("course-mastery-status").hidden = true; byId("course-mastery-content").hidden = false;
  } catch (error) { byId("course-mastery-status").hidden = true; byId("course-mastery-error").hidden = false; byId("course-mastery-error").querySelector("p").textContent = error.message; }
}
byId("mastery-filter")?.addEventListener("change", renderTopics);
byId("mastery-cora-insight-btn")?.addEventListener("click", async event => {
  const button = event.target, para = byId("mastery-cora-insight");
  button.disabled = true; button.textContent = "Asking Cora…";
  try {
    const insight = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/mastery/insight/`, {method:"POST", body: JSON.stringify({})});
    para.textContent = `${insight.insight} ${insight.recommended_action}`; para.hidden = false;
  } catch (error) {
    para.textContent = error.message; para.hidden = false;
  } finally { button.disabled = false; button.textContent = "Ask Cora to explain"; }
});
byId("mastery-rebuild")?.addEventListener("click", async event => { event.target.disabled = true; event.target.textContent = "Rebuilding…"; try { await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/mastery/rebuild/`, {method:"POST"}); await load(); } catch(error) { byId("course-mastery-error").hidden = false; byId("course-mastery-error").querySelector("p").textContent = error.message; } finally { event.target.disabled = false; event.target.textContent = "Rebuild from activity"; } });
byId("course-mastery-error")?.querySelector("button")?.addEventListener("click", load);
if (courseId) { initCourseHeader(courseId); load(); }
