import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();
const root = document.querySelector(".practice-page");
const courseId = root?.dataset.courseId;
const attemptId = root?.dataset.attemptId;
const coursePractice = root?.dataset.coursePractice === "true";
const $ = id => document.getElementById(id);
let state = null;
let course = {};
let busy = false;

function alertMessage(message, error = false) {
  const element = $("pa-alert");
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle("is-error", error);
}

function announce(message) {
  $("pa-save-status").textContent = "";
  requestAnimationFrame(() => { $("pa-save-status").textContent = message; });
}

function setView(view) {
  ["loading", "error", "content"].forEach(name => { $("pa-" + name).hidden = name !== view; });
}

function friendlyError(error, fallback = "Something went wrong. Please try again.") {
  if (error?.status === 404) return "This quiz could not be found or is no longer available.";
  if (error?.status === 409) return "This quiz has already been submitted. Refresh to see the latest results.";
  return fallback;
}

function elapsed() {
  if (!state?.started_at) return;
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(state.started_at).getTime()) / 1000));
  $("pa-timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderNavigator(questions) {
  const grid = $("pa-grid");
  grid.replaceChildren();
  questions.forEach((question, index) => {
    const button = document.createElement("button");
    const answered = question.user_answer !== null && question.user_answer !== undefined;
    const current = index === state.position;
    button.type = "button";
    button.className = [answered ? "answered" : "unanswered", current ? "current" : "", question.flagged ? "flagged" : ""].filter(Boolean).join(" ");
    button.setAttribute("aria-label", `Question ${index + 1}, ${current ? "current, " : ""}${answered ? "answered" : "unanswered"}${question.flagged ? ", bookmarked" : ""}`);
    if (current) button.setAttribute("aria-current", "step");
    const number = document.createElement("span");
    number.textContent = String(index + 1);
    button.append(number);
    if (answered) {
      const check = document.createElement("i");
      check.textContent = "✓";
      check.setAttribute("aria-hidden", "true");
      button.append(check);
    }
    if (question.flagged) {
      const bookmark = document.createElement("b");
      bookmark.textContent = "★";
      bookmark.setAttribute("aria-hidden", "true");
      button.append(bookmark);
    }
    button.addEventListener("click", () => move(index));
    grid.append(button);
  });
}

function renderChoices(current) {
  const choices = $("pa-choices");
  choices.replaceChildren();
  current.choices.forEach((choice, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    const radio = document.createElement("span");
    const copy = document.createElement("span");
    const letter = document.createElement("b");
    const text = document.createElement("strong");
    input.type = "radio";
    input.name = "answer";
    input.value = choice;
    input.checked = current.user_answer === choice;
    input.disabled = state.finalized || busy;
    input.setAttribute("aria-label", `Answer ${String.fromCharCode(65 + index)}: ${choice}`);
    input.addEventListener("change", () => save({ user_answer: choice }, "Answer saved."));
    radio.className = "answer-radio";
    copy.className = "answer-copy";
    letter.textContent = `${String.fromCharCode(65 + index)}.`;
    text.textContent = choice;
    copy.append(letter, text);
    label.append(input, radio, copy);
    if (state.finalized) {
      label.classList.toggle("correct", choice === current.correct_answer);
      label.classList.toggle("incorrect", current.user_answer === choice && !current.correct);
    }
    choices.append(label);
  });
}

function render() {
  setView("content");
  const questions = state.questions || [];
  const current = questions[state.position];
  const completion = questions.length ? Math.round(state.answered_count / questions.length * 100) : 0;
  const positionProgress = questions.length ? Math.round((state.position + 1) / questions.length * 100) : 0;
  const courseName = course.name || state.course_name || courseId.toUpperCase();
  $("pa-title").textContent = coursePractice ? "Practice Quiz" : `${state.title} Practice Quiz`;
  $("pa-course").textContent = courseName;
  $("pa-course-code").textContent = course.code || courseName;
  $("pa-course-name").textContent = courseName;
  $("pa-question-meta").textContent = `Question ${Math.min(state.position + 1, questions.length)} of ${questions.length}`;
  $("pa-percent").textContent = `${completion}%`;
  $("pa-answered").textContent = `${state.answered_count} / ${questions.length}`;
  $("pa-ring").style.setProperty("--progress", `${completion * 3.6}deg`);
  $("pa-ring").setAttribute("aria-label", `${completion} percent complete`);
  $("pa-progress").style.width = `${positionProgress}%`;
  $("pa-progress").parentElement.setAttribute("aria-valuenow", String(positionProgress));
  renderNavigator(questions);

  if (!current) {
    $("pa-question").textContent = "No supported questions were generated for this attempt.";
    $("pa-submit").disabled = true;
    return;
  }

  $("pa-topic").textContent = current.topic || "Course topic";
  $("pa-source").textContent = current.source_label || "Confirmed course material";
  $("pa-question").textContent = current.question;
  renderChoices(current);
  const bookmark = $("pa-flag");
  bookmark.setAttribute("aria-pressed", String(current.flagged));
  bookmark.classList.toggle("active", current.flagged);
  bookmark.querySelector("span").textContent = current.flagged ? "★" : "☆";
  bookmark.disabled = state.finalized || busy;
  $("pa-previous").disabled = state.position === 0 || busy;
  $("pa-submit").disabled = busy || (!state.finalized && !current.user_answer);
  $("pa-submit").innerHTML = state.finalized
    ? (state.position === questions.length - 1 ? "Review complete" : "Next result <span aria-hidden='true'>&rarr;</span>")
    : (state.position === questions.length - 1 ? "Submit quiz <span aria-hidden='true'>&rarr;</span>" : "Next question <span aria-hidden='true'>&rarr;</span>");
  const coraQuestion = `Explain the concept behind this practice question without revealing which option is correct: ${current.question}`;
  $("pa-cora").href = `/cora/?course=${encodeURIComponent(courseId)}&q=${encodeURIComponent(coraQuestion)}`;

  const result = $("pa-result");
  result.hidden = !state.finalized;
  if (state.finalized) {
    result.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = current.correct ? "Correct" : (current.user_answer ? `Correct answer: ${current.correct_answer}` : `Unanswered · Correct answer: ${current.correct_answer}`);
    const explanation = document.createElement("p");
    explanation.textContent = current.explanation || "No additional explanation was available in the source.";
    result.append(strong, explanation);
  }
}

async function save(changes, successMessage = "") {
  if (busy || state.finalized) return false;
  busy = true;
  try {
    state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/`, {
      method: "PATCH",
      body: JSON.stringify({ question_id: state.questions[state.position].question_id, ...changes }),
    });
    alertMessage("");
    if (successMessage) announce(successMessage);
    return true;
  } catch (error) {
    alertMessage(friendlyError(error, "We couldn't save that change. Please try again."), true);
    return false;
  } finally {
    busy = false;
    render();
  }
}

async function move(position) {
  if (busy || position < 0 || position >= state.questions.length) return;
  if (state.finalized) {
    state.position = position;
    render();
    return;
  }
  await save({ position });
}

async function next() {
  if (busy) return;
  if (state.finalized) {
    if (state.position < state.questions.length - 1) move(state.position + 1);
    return;
  }
  const current = state.questions[state.position];
  if (!current?.user_answer) {
    alertMessage("Choose an answer before continuing.", true);
    document.querySelector("#pa-choices input")?.focus();
    return;
  }
  if (state.position < state.questions.length - 1) {
    await move(state.position + 1);
    return;
  }
  const unanswered = state.questions.filter(question => !question.user_answer).length;
  const message = unanswered
    ? `Submit this practice quiz with ${unanswered} unanswered question${unanswered === 1 ? "" : "s"}?`
    : "Submit this practice quiz? You will not be able to change answers afterward.";
  if (!window.confirm(message)) return;
  busy = true;
  try {
    state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/finalize/`, { method: "POST" });
    alertMessage(`Submitted: ${state.summary.correct} of ${state.summary.total} correct.`);
    announce("Practice quiz submitted. Answers and grounded explanations are now available.");
  } catch (error) {
    alertMessage(friendlyError(error, "We couldn't submit your quiz. Your saved answers are still here."), true);
  } finally {
    busy = false;
    render();
  }
}

async function load() {
  setView("loading");
  alertMessage("");
  try {
    const [attempt, header] = await Promise.all([
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/quizzes/attempts/${attemptId}/`),
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/header/`),
    ]);
    state = attempt;
    course = header.course || {};
    if (state.status === "preparing") throw new Error("preparing");
    render();
    elapsed();
  } catch (error) {
    setView("error");
    $("pa-error").querySelector("p").textContent = error?.message === "preparing"
      ? "This quiz is still being prepared. Try again in a moment."
      : friendlyError(error, "Something went wrong while loading your saved attempt.");
  }
}

$("pa-retry")?.addEventListener("click", load);
$("pa-previous")?.addEventListener("click", () => move(state.position - 1));
$("pa-submit")?.addEventListener("click", next);
$("pa-flag")?.addEventListener("click", () => save({ flagged: !state.questions[state.position].flagged }, state.questions[state.position].flagged ? "Bookmark removed." : "Question bookmarked."));
document.addEventListener("keydown", event => {
  if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(event.target.tagName)) return;
  if (!state) return;
  if (event.key === "ArrowLeft") move(state.position - 1);
  if (event.key === "ArrowRight") move(state.position + 1);
  const choiceIndex = Number(event.key) - 1;
  if (choiceIndex >= 0 && choiceIndex < 4 && !state.finalized) document.querySelectorAll("#pa-choices input")[choiceIndex]?.click();
});

setInterval(elapsed, 1000);
load();
