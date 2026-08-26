import { apiRequest } from "./core/api.js";

const root = document.querySelector(".practice-page");
const courseId = root?.dataset.courseId;
const quizId = root?.dataset.quizId;
const attemptId = root?.dataset.attemptId;
const $ = id => document.getElementById(id);
let state = null;
let busy = false;

function alertMessage(message, error = false) { const el = $("pa-alert"); el.textContent = message; el.hidden = !message; el.classList.toggle("is-error", error); }
function setView(view) { ["loading", "error", "content"].forEach(name => $("pa-" + name).hidden = name !== view); }
function errorText(error) { return error?.message || "Something went wrong."; }
function elapsed() { if (!state) return; const seconds = Math.max(0, Math.floor((Date.now() - new Date(state.started_at).getTime()) / 1000)); $("pa-timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`; }

function render() {
  setView("content"); const questions = state.questions || []; const current = questions[state.position];
  $("pa-title").textContent = `${state.title} Practice Exam`; $("pa-course").textContent = state.course_name; $("pa-exam").textContent = state.title;
  const percent = questions.length ? Math.round(state.answered_count / questions.length * 100) : 0;
  $("pa-question-meta").textContent = `Question ${state.position + 1} of ${questions.length}`; $("pa-percent").textContent = `${percent}% complete`; $("pa-progress").style.width = `${percent}%`;
  $("pa-detail-count").textContent = `▤ ${questions.length} questions`; $("pa-detail-time").textContent = `◷ ${state.duration_minutes || "Untimed"} minutes`; $("pa-detail-topics").textContent = `◇ ${new Set(questions.map(q => q.topic)).size} topics`;
  const grid = $("pa-grid"); grid.replaceChildren(); questions.forEach((question, index) => { const button = document.createElement("button"); button.type = "button"; button.textContent = index + 1; button.className = `${question.user_answer ? "answered" : ""} ${index === state.position ? "current" : ""} ${question.flagged ? "flagged" : ""}`; button.setAttribute("aria-label", `Question ${index + 1}${question.flagged ? ", flagged" : ""}`); button.addEventListener("click", () => move(index)); grid.append(button); });
  if (!current) return;
  $("pa-topic").textContent = current.topic; $("pa-source").textContent = current.source_label; $("pa-question").textContent = current.question;
  const choices = $("pa-choices"); choices.replaceChildren(); current.choices.forEach((choice, index) => { const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = "answer"; input.value = choice; input.checked = current.user_answer === choice; input.disabled = state.finalized; input.addEventListener("change", () => save({ user_answer: choice })); const mark = document.createElement("span"); mark.textContent = String.fromCharCode(65 + index); const text = document.createElement("strong"); text.textContent = choice; label.append(input, mark, text); if (state.finalized) label.classList.toggle("correct", choice === current.correct_answer); choices.append(label); });
  $("pa-flag").setAttribute("aria-pressed", String(current.flagged)); $("pa-flag").classList.toggle("active", current.flagged); $("pa-flag").disabled = state.finalized;
  $("pa-previous").disabled = state.position === 0; $("pa-submit").textContent = state.finalized ? (state.position === questions.length - 1 ? "Review complete" : "Next result") : (state.position === questions.length - 1 ? "Submit exam" : "Next question");
  const result = $("pa-result"); result.hidden = !state.finalized; if (state.finalized) { result.replaceChildren(); const strong = document.createElement("strong"); strong.textContent = current.correct ? "Correct" : `Correct answer: ${current.correct_answer}`; const p = document.createElement("p"); p.textContent = current.explanation || "No additional explanation was available in the source."; result.append(strong, p); }
}

async function save(changes) { if (busy || state.finalized) return; busy = true; try { state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/`, { method: "PATCH", body: JSON.stringify({ question_id: state.questions[state.position].question_id, ...changes }) }); render(); } catch (error) { alertMessage(errorText(error), true); } finally { busy = false; } }
async function move(position) { if (busy || position < 0 || position >= state.questions.length) return; if (state.finalized) { state.position = position; render(); return; } await save({ position }); }
async function next() { if (state.finalized) { if (state.position < state.questions.length - 1) move(state.position + 1); return; } if (state.position < state.questions.length - 1) return move(state.position + 1); if (busy) return; busy = true; try { state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/finalize/`, { method: "POST" }); render(); alertMessage(`Submitted: ${state.summary.correct} of ${state.summary.total} correct.`); } catch (error) { alertMessage(errorText(error), true); } finally { busy = false; } }
async function load() { setView("loading"); alertMessage(""); try { state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/`); if (state.status === "preparing") throw new Error("This attempt is still being prepared. Try again in a moment."); render(); elapsed(); } catch (error) { setView("error"); $("pa-error").querySelector("p").textContent = errorText(error); } }

$("pa-retry")?.addEventListener("click", load); $("pa-previous")?.addEventListener("click", () => move(state.position - 1)); $("pa-submit")?.addEventListener("click", next); $("pa-flag")?.addEventListener("click", () => save({ flagged: !state.questions[state.position].flagged }));
document.addEventListener("keydown", event => { if (["INPUT", "TEXTAREA"].includes(event.target.tagName)) return; if (event.key === "ArrowLeft") move(state.position - 1); if (event.key === "ArrowRight") move(state.position + 1); });
setInterval(elapsed, 1000); load();
