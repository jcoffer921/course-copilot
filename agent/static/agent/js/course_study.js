import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";
import { initCourseHeader } from "./core/course_header.js";

initNavigation();
const root = document.querySelector("[data-page-section='course-study']");
const courseId = root?.dataset.courseId;
const byId = id => document.getElementById(id);
let recommendation = null;

function destination(view, topic = "", resume = "") {
  const params = new URLSearchParams({ course: courseId, view });
  if (topic) params.set("topic", topic);
  if (resume) params.set("resume", resume);
  return `/study/?${params}`;
}

function setTopicLinks(topic) {
  const quizLink = byId("start-quiz");
  quizLink.href = `/courses/${encodeURIComponent(courseId)}/study/quiz/${topic ? `?topic=${encodeURIComponent(topic)}` : ""}`;
  quizLink.textContent = "Start practice quiz";
  byId("review-flashcards").href = `/courses/${encodeURIComponent(courseId)}/study/flashcards/due/`;
  byId("study-quiz-topic").textContent = topic || "Choose a topic";
}

function renderHistory(sessions) {
  const host = byId("study-history");
  if (!sessions.length) { host.innerHTML = '<p class="learning-empty">No study activity yet. Start with the recommended session.</p>'; return; }
  host.replaceChildren(...sessions.slice(0, 5).map(session => {
    const row = document.createElement("div"); row.className = "study-history-row";
    const copy = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = `${session.topic || "Course"} ${session.mode} session`;
    const state = document.createElement("span"); state.textContent = session.status === "in_progress" ? "Ready to continue" : "Completed";
    const date = document.createElement("time"); date.textContent = new Date(session.completed_at || session.started_at).toLocaleDateString();
    copy.append(title, state); row.append(copy, date);
    if (session.status === "in_progress") { const link = document.createElement("a"); link.href = destination("session", session.topic, session.session_id); link.textContent = "Continue"; row.append(link); }
    return row;
  }));
}

function renderDue(cards) {
  byId("study-due-count").textContent = cards.length;
  const counts = new Map();
  cards.forEach(card => { const topic = card.topic || "Other"; counts.set(topic, (counts.get(topic) || 0) + 1); });
  const list = byId("study-due-topics");
  list.replaceChildren(...[...counts].slice(0, 4).map(([topic, count]) => { const li = document.createElement("li"); li.textContent = `${topic}: ${count}`; return li; }));
  if (!counts.size) { const li = document.createElement("li"); li.textContent = "No cards are due right now."; list.append(li); }
}

function renderRecommendation(items, topics) {
  recommendation = items.find(item => item.course_id === courseId) || null;
  const topic = recommendation?.topic || topics[0] || "Course foundations";
  byId("study-rec-topic").textContent = `${topic} review`;
  byId("study-rec-reason").textContent = recommendation?.reason || (topics.length ? "A useful starter session from your confirmed course topics." : "Upload and confirm course material to unlock grounded study tools.");
  const duration = Number(document.querySelector("input[name='duration']:checked")?.value || 45);
  const steps = duration <= 15 ? [["Flashcard review", `${duration} min`]] : duration <= 30 ? [["Flashcards", "10 min"], ["Practice quiz", `${duration - 10} min`]] : [["Flashcards", "10 min"], ["Practice quiz", "20 min"], ["Short recall", `${duration - 30} min`]];
  byId("study-rec-steps").replaceChildren(...steps.map(([name, time]) => { const li = document.createElement("li"); li.innerHTML = `<strong>${name}</strong><span>${time}</span>`; return li; }));
  byId("study-rec-time").textContent = `${duration} min`;
  setTopicLinks(topic);
}

async function start(topic, duration, mode) {
  const feedback = byId("study-feedback"); const buttons = root.querySelectorAll("button[type='submit'],#start-recommended");
  buttons.forEach(button => button.disabled = true); feedback.hidden = false; feedback.textContent = "Starting your grounded study session…";
  try {
    const session = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/`, { method: "POST", body: JSON.stringify({ topic, duration_minutes: duration, mode }) });
    feedback.innerHTML = `Session ready. <a href="${destination("session", topic, session.session_id)}">Continue studying</a>`;
    await load();
  } catch (error) { feedback.textContent = error.message; feedback.classList.add("error"); }
  finally { buttons.forEach(button => button.disabled = false); }
}

async function load() {
  byId("course-study-error").hidden = true;
  try {
    const [syllabus, recs, due, history, header] = await Promise.all([
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/syllabus/`).catch(error => error.status === 404 ? { topics: [] } : Promise.reject(error)),
      apiRequest("/api/recommendations/?limit=50"),
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/flashcards/due/?limit=100`),
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/?limit=10`),
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/header/`),
    ]);
    const topics = syllabus.topics || [];
    const select = byId("study-topic"); select.replaceChildren();
    const recommended = document.createElement("option"); recommended.value = ""; recommended.textContent = "Recommended"; select.append(recommended);
    topics.forEach(topic => { const option = document.createElement("option"); option.value = topic; option.textContent = topic; select.append(option); });
    const requestedTopic = new URLSearchParams(location.search).get("topic");
    if (requestedTopic && topics.includes(requestedTopic)) select.value = requestedTopic;
    byId("course-study-title").textContent = `Study ${header.course.name || courseId}`;
    renderRecommendation(recs.recommendations || [], topics); renderDue(due.cards || []); renderHistory(history.sessions || []);
    if (select.value) setTopicLinks(select.value);
    byId("course-study-status").hidden = true; byId("course-study-content").hidden = false;
  } catch (error) { byId("course-study-status").hidden = true; byId("course-study-error").hidden = false; byId("course-study-error").querySelector("p").textContent = error.message; }
}

root?.addEventListener("change", event => {
  if (event.target.id === "study-topic") setTopicLinks(event.target.value || recommendation?.topic || "");
  if (event.target.name === "duration") renderRecommendation(recommendation ? [recommendation] : [], [...byId("study-topic").options].slice(1).map(o => o.value));
});
root?.addEventListener("submit", event => { if (event.target.id !== "course-study-start") return; event.preventDefault(); start(byId("study-topic").value || recommendation?.topic || "", Number(new FormData(event.target).get("duration")), byId("study-mode").value); });
byId("start-recommended")?.addEventListener("click", () => start(recommendation?.topic || byId("study-topic").options[1]?.value || "", Number(document.querySelector("input[name='duration']:checked").value), recommendation?.suggested_mode || "mixed"));
byId("course-study-error")?.querySelector("button")?.addEventListener("click", load);
if (courseId) { initCourseHeader(courseId); load(); }
