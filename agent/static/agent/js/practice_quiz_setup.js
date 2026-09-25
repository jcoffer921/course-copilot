import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();
const root = document.querySelector("[data-page-section='practice-quiz-setup']");
const courseId = root?.dataset.courseId;
const byId = id => document.getElementById(id);
const MIN_QUESTIONS = 1;
const MAX_QUESTIONS = 20;
let topics = [];
let submitting = false;
let retryAction = null;
let generationTimers = [];

const GENERATION_PHASES = [
  { delay: 0, progress: 12, message: "Reading confirmed course materials..." },
  { delay: 1800, progress: 30, message: "Selecting topics from your quiz scope..." },
  { delay: 4200, progress: 58, message: count => `Generating ${count} grounded questions...` },
  { delay: 7800, progress: 80, message: "Checking answer choices and explanations..." },
  { delay: 11500, progress: 94, message: "Putting your practice quiz together..." },
];

function renderGenerationPhase(index, questionCount) {
  const phase = GENERATION_PHASES[index];
  byId("qs-generation-status").textContent = typeof phase.message === "function" ? phase.message(questionCount) : phase.message;
  document.querySelector(".quiz-generation-progress span").style.width = `${phase.progress}%`;
  document.querySelectorAll("[data-generation-step]").forEach((step, stepIndex) => {
    step.classList.toggle("active", stepIndex === index);
    step.classList.toggle("visited", stepIndex < index);
  });
}

function startGenerationNarration(questionCount) {
  generationTimers.forEach(clearTimeout);
  generationTimers = [];
  const overlay = byId("qs-generation-overlay");
  overlay.hidden = false;
  document.body.classList.add("quiz-is-generating");
  renderGenerationPhase(0, questionCount);
  overlay.focus();
  GENERATION_PHASES.slice(1).forEach((phase, offset) => {
    generationTimers.push(setTimeout(() => renderGenerationPhase(offset + 1, questionCount), phase.delay));
  });
}

function stopGenerationNarration() {
  generationTimers.forEach(clearTimeout);
  generationTimers = [];
  byId("qs-generation-overlay").hidden = true;
  document.body.classList.remove("quiz-is-generating");
}

function setError({ insufficient = false } = {}, retry = null) {
  byId("qs-error-title").textContent = insufficient ? "Not enough course material yet" : "We couldn't prepare your quiz.";
  byId("qs-error-message").textContent = insufficient
    ? "Upload notes or confirm your syllabus before creating a grounded quiz."
    : "Something went wrong while preparing your course materials.";
  retryAction = retry;
  byId("qs-retry").hidden = !retry;
  byId("qs-error").hidden = false;
}

function clearError() {
  byId("qs-error").hidden = true;
  retryAction = null;
}

function setCount(rawCount) {
  const parsed = Number(rawCount);
  const count = Number.isFinite(parsed) ? Math.min(MAX_QUESTIONS, Math.max(MIN_QUESTIONS, Math.round(parsed))) : 10;
  byId("qs-count").value = String(count);
  byId("qs-decrement").disabled = submitting || count <= MIN_QUESTIONS;
  byId("qs-increment").disabled = submitting || count >= MAX_QUESTIONS;
  document.querySelectorAll("#qs-presets button").forEach(button => {
    const selected = Number(button.dataset.count) === count;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  return count;
}

function setScope(value) {
  document.querySelectorAll("input[name='scope']").forEach(input => {
    const selected = input.value === value;
    input.checked = selected;
    input.closest(".quiz-choice-card")?.classList.toggle("selected", selected);
  });
  byId("qs-topic-field").hidden = value !== "topic";
  byId("qs-topic").required = value === "topic";
  if (value === "topic") byId("qs-topic").focus();
}

function setSubmitting(value) {
  submitting = value;
  const button = byId("qs-start");
  button.disabled = value;
  button.innerHTML = value ? "Preparing your quiz..." : "Start practice quiz <span aria-hidden='true'>&rarr;</span>";
  byId("qs-form").setAttribute("aria-busy", String(value));
  document.querySelectorAll("#qs-form input, #qs-form select, #qs-form button:not(#qs-start)").forEach(control => { control.disabled = value; });
  if (value) startGenerationNarration(Number(byId("qs-count").value));
  else {
    stopGenerationNarration();
    setCount(byId("qs-count").value);
  }
}

async function load() {
  clearError();
  byId("qs-loading").hidden = false;
  byId("qs-form").hidden = true;
  byId("qs-empty").hidden = true;
  try {
    const [header, syllabus] = await Promise.all([
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/header/`),
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/syllabus/`).catch(error => error.status === 404 ? { quiz_topics: [] } : Promise.reject(error)),
    ]);
    const course = header.course || {};
    topics = syllabus.quiz_topics || [];
    const courseName = course.name || courseId.toUpperCase();
    byId("qs-code").textContent = course.code || courseName;
    byId("qs-course-name").textContent = courseName;
    byId("qs-course-link").textContent = courseName;
    byId("qs-topic").replaceChildren(...topics.map(topic => {
      const option = document.createElement("option");
      option.value = topic;
      option.textContent = topic;
      return option;
    }));
    byId("qs-loading").hidden = true;
    if (!topics.length) {
      byId("qs-empty").hidden = false;
      return;
    }
    const requested = new URL(location.href).searchParams.get("topic");
    if (requested && topics.includes(requested)) {
      byId("qs-topic").value = requested;
      setScope("topic");
    } else {
      setScope("course");
    }
    setCount(10);
    byId("qs-form").hidden = false;
  } catch (_) {
    byId("qs-loading").hidden = true;
    setError({}, load);
  }
}

async function startQuiz() {
  if (submitting) return;
  clearError();
  const count = Number(byId("qs-count").value);
  if (!Number.isInteger(count) || count < MIN_QUESTIONS || count > MAX_QUESTIONS) {
    setError({}, () => byId("qs-count").focus());
    byId("qs-error-message").textContent = `Choose between ${MIN_QUESTIONS} and ${MAX_QUESTIONS} questions.`;
    byId("qs-count").focus();
    return;
  }
  const topicScope = document.querySelector("input[name='scope']:checked")?.value === "topic";
  const selectedTopic = byId("qs-topic").value;
  if (topicScope && !topics.includes(selectedTopic)) {
    setError({ insufficient: true });
    return;
  }
  const body = { question_count: count };
  if (topicScope) body.topics = [selectedTopic];
  setSubmitting(true);
  try {
    const attempt = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/course-practice/attempts/`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    location.assign(`/courses/${encodeURIComponent(courseId)}/study/quizzes/course-practice/attempts/${encodeURIComponent(attempt.attempt_id)}/`);
  } catch (error) {
    setSubmitting(false);
    setError({ insufficient: error.status === 400 || error.status === 422 }, startQuiz);
  }
}

byId("qs-decrement")?.addEventListener("click", () => setCount(Number(byId("qs-count").value) - 1));
byId("qs-increment")?.addEventListener("click", () => setCount(Number(byId("qs-count").value) + 1));
byId("qs-count")?.addEventListener("input", () => setCount(byId("qs-count").value));
document.querySelectorAll("#qs-presets button").forEach(button => button.addEventListener("click", () => setCount(button.dataset.count)));
document.querySelectorAll("input[name='scope']").forEach(input => input.addEventListener("change", () => setScope(input.value)));
byId("qs-retry")?.addEventListener("click", () => retryAction?.());
byId("qs-form")?.addEventListener("submit", event => { event.preventDefault(); startQuiz(); });
document.addEventListener("keydown", event => {
  if (submitting && event.key === "Tab") {
    event.preventDefault();
    byId("qs-generation-overlay").focus();
  }
});

if (courseId) load();
