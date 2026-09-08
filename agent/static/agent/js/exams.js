import { initNavigation } from "./core/navigation.js";
import { apiRequest } from "./core/api.js";

initNavigation();
const $ = id => document.getElementById(id);
const root = document.querySelector("[data-page-section='exam']");
const courseId = root?.dataset.courseId; const examId = root?.dataset.examId;
const state = { workspace: null, practiceQuestion: null, lastFocus: null };
const base = () => `/api/courses/${encodeURIComponent(courseId)}/exams/${encodeURIComponent(examId)}`;
const errorMessage = error => error?.data?.detail || error?.message || "Something went wrong.";

function countdown(days) { if (days < 0) return `${Math.abs(days)} days ago`; if (days === 0) return "Today"; if (days === 1) return "Tomorrow"; return `${days} days`; }
function status(topic) { const score = Math.round((topic.score || 0) * 100); return score >= 70 ? ["strong", "Strong"] : score >= 40 ? ["developing", "Developing"] : ["weak", "Needs review"]; }

function renderTopics(workspace) {
  const included = workspace.topics.filter(topic => topic.included);
  $("exam-topics").replaceChildren(...included.map(topic => {
    const [kind, label] = status(topic); const score = Math.round((topic.score || 0) * 100);
    const link = document.createElement("a"); link.className = `exam-topic-row ${kind}`; link.href = `/courses/${encodeURIComponent(courseId)}/mastery/?topic=${encodeURIComponent(topic.topic)}`;
    link.innerHTML = `<span class="exam-topic-icon" aria-hidden="true">${kind === "strong" ? "✓" : kind === "developing" ? "!" : "↓"}</span><span class="exam-topic-body"><strong>${escapeHtml(topic.topic)}</strong><span class="exam-topic-progress"><i style="width:${score}%"></i></span></span><b>${score}%</b><span class="sr-only">${label}</span>`;
    return link;
  }));
}

function renderPlan(preparation) {
  $("exam-preparation").replaceChildren(...preparation.phases.map(phase => {
    const row = document.createElement("a"); row.className = "exam-phase"; row.href = `/study/?course=${encodeURIComponent(courseId)}&topic=${encodeURIComponent(phase.topic)}`;
    row.innerHTML = `<span class="exam-phase-dot"></span><span><strong>${escapeHtml(phase.label)}</strong><small>${escapeHtml(phase.date_range)}</small></span><span><strong>${escapeHtml(phase.topic)}</strong><small>${phase.blocks} study block${phase.blocks === 1 ? "" : "s"} · ${formatMinutes(phase.minutes)}</small></span><em>${phase.status === "in_progress" ? "In progress" : "Upcoming"}</em>`;
    return row;
  }));
  $("exam-plan-total").textContent = `Total estimated time: ${formatMinutes(preparation.total_minutes)}`;
}

function renderMaterials(workspace) {
  const selected = workspace.materials.filter(item => item.included);
  $("exam-materials").replaceChildren(...(selected.length ? selected.map(material => Object.assign(document.createElement("div"), { className: "exam-material-row", textContent: `${material.original_filename} · ${material.material_type}` })) : [Object.assign(document.createElement("p"), { className: "material-meta", textContent: "No ready, confirmed materials selected." })]));
}

function renderGuide(guide) {
  $("exam-guide-empty").hidden = Boolean(guide); $("exam-guide").hidden = !guide;
  if (!guide) return;
  $("exam-guide").replaceChildren(...guide.sections.map(section => { const node = document.createElement("section"); const list = section.key_points.map(point => `<li>${escapeHtml(point)}</li>`).join(""); node.innerHTML = `<h3>${escapeHtml(section.topic)}</h3><ul>${list}</ul>${section.citation ? `<p class="material-meta">Source: ${escapeHtml(section.citation.title)}</p>` : ""}`; return node; }));
}

function render(workspace) {
  state.workspace = workspace; $("exam-title").textContent = $("exam-crumb-title").textContent = workspace.event.title; $("exam-course-name").textContent = workspace.course_name;
  $("exam-date").textContent = new Date(`${workspace.event.date}T12:00:00`).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" }); $("exam-countdown").textContent = countdown(workspace.days_until);
  $("exam-readiness-score").textContent = `${workspace.readiness.score}%`; $("exam-readiness-ring").style.setProperty("--progress", `${workspace.readiness.score}%`); $("exam-readiness-label").textContent = workspace.readiness.label;
  const strong = workspace.readiness.strong_topics; $("exam-readiness-summary").textContent = strong.length ? `Strongest in ${strong.join(" and ")}; focus next on ${workspace.recommendation?.topic || "mixed review"}.` : "Complete targeted practice to build evidence-backed readiness.";
  renderTopics(workspace); renderPlan(workspace.preparation); renderMaterials(workspace); renderGuide(workspace.plan.study_guide);
  const recommendation = workspace.recommendation; $("exam-recommend-title").textContent = recommendation ? `Start with ${recommendation.topic}` : "Choose an exam topic"; $("exam-recommend-reason").textContent = recommendation?.reason || "Select topics to receive a grounded recommendation.";
  $("exam-recommend-factors").replaceChildren(...(recommendation?.factors || []).map(item => Object.assign(document.createElement("li"), { textContent: item })));
  $("exam-ask-cora").href = `/cora/?q=${encodeURIComponent(`Help me study ${recommendation?.topic || "for this exam"} for ${workspace.event.title}.`)}`;
}

async function load() { $("exam-loading").hidden = false; $("exam-error").hidden = true; $("exam-content").hidden = true; try { render(await apiRequest(base() + "/")); $("exam-loading").hidden = true; $("exam-content").hidden = false; } catch (error) { $("exam-loading").hidden = true; $("exam-error").hidden = false; $("exam-error").querySelector("p").textContent = errorMessage(error); } }
function showAlert(text, error = false) { $("exam-alert").hidden = false; $("exam-alert").textContent = text; $("exam-alert").classList.toggle("error", error); }

function openTopics(event) { state.lastFocus = event.currentTarget; $("exam-topics-editor").replaceChildren(...state.workspace.topics.map(topic => { const label = document.createElement("label"); const input = Object.assign(document.createElement("input"), { type: "checkbox", value: topic.topic, checked: topic.included }); label.append(input, Object.assign(document.createElement("span"), { textContent: topic.topic })); return label; })); $("exam-topics-dialog").hidden = false; $("exam-topics-editor").querySelector("input")?.focus(); }
function closeTopics() { $("exam-topics-dialog").hidden = true; state.lastFocus?.focus(); }
async function saveTopics() { const topics = [...$("exam-topics-editor").querySelectorAll("input:checked")].map(input => input.value); try { await apiRequest(base() + "/plan/", { method: "PATCH", body: JSON.stringify({ included_topics: topics }) }); closeTopics(); await load(); } catch (error) { showAlert(errorMessage(error), true); } }

async function startStudy() { const topic = state.workspace.recommendation?.topic || state.workspace.topics.find(item => item.included)?.topic; if (!topic) return showAlert("Include at least one topic first.", true); const phase = state.workspace.preparation.phases[0]; const duration = phase ? Math.round(phase.minutes / phase.blocks) : 45; try { const session = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/`, { method: "POST", body: JSON.stringify({ topic, duration_minutes: duration, mode: "mixed" }) }); window.location.assign(`/study/?view=session&course=${encodeURIComponent(courseId)}&topic=${encodeURIComponent(topic)}&session=${encodeURIComponent(session.session_id)}`); } catch (error) { showAlert(errorMessage(error), true); } }
async function generateGuide() { $("exam-guide-loading").hidden = false; try { const guide = await apiRequest(base() + "/study-guide/", { method: "POST" }); renderGuide(guide); } catch (error) { showAlert(errorMessage(error), true); } finally { $("exam-guide-loading").hidden = true; } }
async function loadPractice() { const included = state.workspace.topics.filter(item => item.included); if (!included.length) return showAlert("Include at least one topic first.", true); const button = $("exam-practice-start"); button.disabled = true; button.textContent = "Preparing practice exam…"; try { const attempt = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/${encodeURIComponent(examId)}/attempts/`, { method: "POST", body: JSON.stringify({ question_count: Math.min(20, Math.max(5, included.length * 4)) }) }); window.location.assign(`/courses/${encodeURIComponent(courseId)}/study/quizzes/${encodeURIComponent(examId)}/attempts/${encodeURIComponent(attempt.attempt_id)}/`); } catch (error) { showAlert(errorMessage(error), true); button.disabled = false; button.textContent = "Start practice set"; } }
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = value || ""; return div.innerHTML; }
function formatMinutes(minutes) { return minutes >= 60 ? `~${Math.round(minutes / 60)} hours` : `${minutes} minutes`; }

$("exam-retry")?.addEventListener("click", load); $("exam-start-study")?.addEventListener("click", startStudy); document.querySelectorAll(".exam-edit-topics").forEach(button => button.addEventListener("click", openTopics)); $("exam-topics-cancel")?.addEventListener("click", closeTopics); $("exam-topics-save")?.addEventListener("click", saveTopics); $("exam-generate-guide")?.addEventListener("click", generateGuide); $("exam-practice-start")?.addEventListener("click", loadPractice); $("exam-practice-next")?.addEventListener("click", loadPractice); document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("exam-topics-dialog")?.hidden) closeTopics(); });
if (root && courseId && examId) load();
