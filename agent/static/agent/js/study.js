import { initNavigation } from "./core/navigation.js";
import { apiRequest } from "./core/api.js";
import { showToast } from "./core/toast.js";
import "./flashcards.js";
import "./quiz.js";

initNavigation();

const byId = id => document.getElementById(id);

const guidedRoot = byId("guided-session-root");

function errorMessage(error) {
  if (error?.data && typeof error.data === "object") {
    const fieldMessage = Object.values(error.data).flat().find(value => typeof value === "string");
    if (fieldMessage) return fieldMessage;
  }
  return error?.message || "Something went wrong.";
}

function showAlert(message, isError = false) {
  const alert = byId("guided-session-alert");
  if (!alert) return;
  alert.textContent = message;
  alert.classList.toggle("error", isError);
  alert.hidden = false;
}

function clearAlert() {
  const alert = byId("guided-session-alert");
  if (alert) alert.hidden = true;
}

// One fixed rating -> interval ladder (see agent/services/spaced_repetition.py)
// drives how many multiple-choice/short-recall questions a session asks —
// derived from the chosen duration so a 10-minute session doesn't ask as
// much as a 30-minute one.
function sessionTargets(durationMinutes) {
  const minutes = Number(durationMinutes) || 15;
  return {
    flashcardTarget: Math.max(4, Math.min(10, Math.round(minutes / 2))),
    mcTarget: Math.max(3, Math.min(8, Math.round(minutes / 4))),
    recallTarget: 2,
  };
}

const STEP_IDS = ["guided-session-flashcard-step", "guided-session-quiz-step", "guided-session-recall-prompt", "guided-session-summary-step"];

const state = {
  session: null,
  courseTopics: [],
  targets: null,
  flashcards: [],
  flashcardIndex: 0,
  flashcardFlipped: false,
  flashcardsDone: 0,
  quizPhase: null, // "multiple_choice" | "open_ended"
  quizAsked: 0,
  quizAskedQuestions: [],
  currentQuestion: null,
};

// What the panel should currently look like, independent of the live DOM.
// enforceUi() below is the ONLY place that writes `.hidden` — every other
// function just updates this object and calls enforceUi(). That makes the
// panel self-healing against the shared DC shell (support.js/<x-dc>), which
// can replace this whole static subtree at unpredictable points after load
// (its Root component depends on controller.js, loaded later in the same
// deferred module graph) and silently reverts any `hidden` attribute this
// script set earlier. A recurring re-assertion (see the setInterval below)
// means any such reversion is corrected within a fraction of a second
// instead of leaving the panel stuck showing every step at once.
const ui = {
  guidedRootHidden: window.ONTRACK_INITIAL_TAB !== "session",
  setupHidden: false,
  loadingHidden: true,
  activeHidden: true,
  step: null,
  ratingsHidden: true,
  openAnswerHidden: true,
  feedbackHidden: true,
  feedbackSourceHidden: true,
  feedbackSourceHref: "#",
  feedbackSourceTarget: "_self",
};

function enforceUi() {
  const set = (id, hidden) => { const el = byId(id); if (el) el.hidden = hidden; };
  set("guided-session-root", ui.guidedRootHidden);
  set("guided-session-setup", ui.setupHidden);
  set("guided-session-loading", ui.loadingHidden);
  set("guided-session-active", ui.activeHidden);
  STEP_IDS.forEach(id => set(id, id !== ui.step));
  set("guided-session-ratings", ui.ratingsHidden);
  set("guided-session-open-answer-row", ui.openAnswerHidden);
  set("guided-session-feedback", ui.feedbackHidden);
  const sourceLink = byId("guided-session-feedback-source");
  if (sourceLink) {
    sourceLink.hidden = ui.feedbackSourceHidden;
    sourceLink.href = ui.feedbackSourceHref;
    sourceLink.target = ui.feedbackSourceTarget;
  }
}

async function loadCourseOptions() {
  const select = byId("guided-session-course");
  const topicSelect = byId("guided-session-topic");
  if (!select || !topicSelect) return;
  try {
    const dashboard = await apiRequest("/api/dashboard/");
    const entries = Object.entries(dashboard.courses || {}).filter(([, summary]) => !summary.error);
    if (select.options.length === 0) {
      select.replaceChildren(...entries.map(([courseId, summary]) => {
        const option = document.createElement("option");
        option.value = courseId;
        option.textContent = summary.course_name || courseId;
        return option;
      }));
      const preselectCourse = window.ONTRACK_INITIAL_COURSE;
      if (preselectCourse && preselectCourse !== "all" && entries.some(([id]) => id === preselectCourse)) {
        select.value = preselectCourse;
      }
    }
    state.courseTopics = entries.reduce((map, [courseId, summary]) => {
      map[courseId] = (summary.topics || []).map(t => t.topic).filter(Boolean);
      return map;
    }, {});
    if (select.value && topicSelect.options.length <= 1) {
      updateTopicOptions(select.value);
      const preselectTopic = window.ONTRACK_INITIAL_TOPIC;
      if (preselectTopic && (state.courseTopics[select.value] || []).includes(preselectTopic)) {
        topicSelect.value = preselectTopic;
      }
    }
    select.addEventListener("change", () => updateTopicOptions(select.value));
  } catch (error) {
    showAlert(errorMessage(error), true);
  }

  function updateTopicOptions(courseId) {
    const topics = state.courseTopics[courseId] || [];
    topicSelect.replaceChildren(
      Object.assign(document.createElement("option"), { value: "", textContent: "All topics" }),
      ...topics.map(topic => Object.assign(document.createElement("option"), { value: topic, textContent: topic })),
    );
  }
}

function updateProgressLabel(text) {
  const label = byId("guided-session-progress-label");
  if (label) label.textContent = text;
}

async function startSession(event) {
  event.preventDefault();
  clearAlert();
  const courseId = byId("guided-session-course").value;
  if (!courseId) { showAlert("Choose a course first.", true); return; }
  const topic = byId("guided-session-topic").value;
  const durationMinutes = Number(byId("guided-session-duration").value);
  const mode = byId("guided-session-mode").value;

  ui.loadingHidden = false;
  enforceUi();
  try {
    const session = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/`, {
      method: "POST",
      body: JSON.stringify({ topic, duration_minutes: durationMinutes, mode }),
    });
    state.session = { ...session, course_id: courseId, topic, mode };
    state.targets = sessionTargets(durationMinutes);
    state.flashcardsDone = 0;
    state.quizAsked = 0;
    state.quizAskedQuestions = [];

    ui.setupHidden = true;
    ui.activeHidden = false;
    enforceUi();

    if (mode === "quiz") {
      await beginQuizPhase("multiple_choice");
    } else {
      await beginFlashcardPhase();
    }
  } catch (error) {
    showAlert(errorMessage(error), true);
  } finally {
    ui.loadingHidden = true;
    enforceUi();
  }
}

async function resumeSession() {
  const params = new URLSearchParams(location.search);
  const sessionId = params.get("resume");
  const courseId = params.get("course");
  if (!sessionId || !courseId || window.ONTRACK_INITIAL_TAB !== "session") return;
  ui.loadingHidden = false; enforceUi();
  try {
    const session = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/sessions/${encodeURIComponent(sessionId)}/`);
    if (session.status !== "in_progress") throw new Error("This study session is no longer active.");
    state.session = session;
    state.targets = sessionTargets(session.duration_minutes || 45);
    state.flashcardsDone = session.activities.filter(item => item.kind === "flashcard_reviewed").length;
    state.quizAsked = session.activities.filter(item => item.kind === "quiz_answered").length;
    state.quizAskedQuestions = [];
    ui.setupHidden = true; ui.activeHidden = false; enforceUi();
    if (session.mode === "quiz") await beginQuizPhase("multiple_choice"); else await beginFlashcardPhase();
  } catch (error) { showAlert(errorMessage(error), true); }
  finally { ui.loadingHidden = true; enforceUi(); }
}

async function recordActivity(kind, payload) {
  try {
    await apiRequest(`/api/courses/${encodeURIComponent(state.session.course_id)}/study/sessions/${state.session.session_id}/activities/`, {
      method: "POST",
      body: JSON.stringify({ kind, payload }),
    });
  } catch (_) {
    // Session-history logging is best-effort; it must never block study flow.
  }
}

async function beginFlashcardPhase() {
  ui.step = "guided-session-flashcard-step";
  enforceUi();
  updateProgressLabel(`Flashcards · 0 / ${state.targets.flashcardTarget}`);
  try {
    const deck = await apiRequest(`/api/courses/${encodeURIComponent(state.session.course_id)}/flashcards/generate/`, {
      method: "POST",
      body: JSON.stringify({ topic: state.session.topic || undefined, count: state.targets.flashcardTarget }),
    });
    state.flashcards = deck.flashcards || [];
    state.flashcardIndex = 0;
    showFlashcard();
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

function showFlashcard() {
  state.flashcardFlipped = false;
  ui.ratingsHidden = true;
  enforceUi();
  const card = state.flashcards[state.flashcardIndex];
  if (!card) { finishFlashcardPhase(); return; }
  byId("guided-session-flashcard-text").textContent = card.term;
  updateProgressLabel(`Flashcards · ${state.flashcardsDone} / ${state.targets.flashcardTarget}`);
}

function flipFlashcard() {
  const card = state.flashcards[state.flashcardIndex];
  if (!card) return;
  state.flashcardFlipped = !state.flashcardFlipped;
  byId("guided-session-flashcard-text").textContent = state.flashcardFlipped ? card.definition : card.term;
  ui.ratingsHidden = !state.flashcardFlipped;
  enforceUi();
}

async function rateFlashcard(rating) {
  const card = state.flashcards[state.flashcardIndex];
  if (!card) return;
  try {
    await apiRequest(`/api/courses/${encodeURIComponent(state.session.course_id)}/flashcards/review/`, {
      method: "POST",
      body: JSON.stringify({ key: card.key, rating }),
    });
  } catch (error) {
    showToast(errorMessage(error), "error");
  }
  await recordActivity("flashcard_reviewed", { key: card.key, rating });

  state.flashcardsDone += 1;
  state.flashcardIndex += 1;
  if (state.flashcardsDone >= state.targets.flashcardTarget || state.flashcardIndex >= state.flashcards.length) {
    finishFlashcardPhase();
  } else {
    showFlashcard();
  }
}

async function finishFlashcardPhase() {
  if (state.session.mode === "flashcards") {
    await finishSession();
  } else {
    await beginQuizPhase("multiple_choice");
  }
}

async function beginQuizPhase(questionType) {
  state.quizPhase = questionType;
  state.quizAsked = 0;
  ui.step = "guided-session-quiz-step";
  enforceUi();
  await loadNextQuestion();
}

async function loadNextQuestion() {
  const target = state.quizPhase === "multiple_choice" ? state.targets.mcTarget : state.targets.recallTarget;
  updateProgressLabel(`${state.quizPhase === "multiple_choice" ? "Quiz" : "Short recall"} · ${state.quizAsked} / ${target}`);
  ui.feedbackHidden = true;
  ui.openAnswerHidden = state.quizPhase !== "open_ended";
  enforceUi();
  byId("guided-session-open-answer").value = "";

  try {
    const question = await apiRequest(`/api/courses/${encodeURIComponent(state.session.course_id)}/quiz/generate/`, {
      method: "POST",
      body: JSON.stringify({
        topic: state.session.topic || undefined,
        question_type: state.quizPhase,
        previous_questions: state.quizAskedQuestions,
      }),
    });
    state.currentQuestion = question;
    byId("guided-session-question").textContent = question.question;
    renderChoices(question);
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

function renderChoices(question) {
  const container = byId("guided-session-choices");
  container.replaceChildren();
  if (!question.choices || question.choices.length === 0) return;
  question.choices.forEach(choice => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-secondary";
    button.textContent = choice;
    button.addEventListener("click", () => submitAnswer(choice));
    container.append(button);
  });
}

async function submitAnswer(answer) {
  const question = state.currentQuestion;
  if (!question || !answer.trim()) return;
  clearAlert();
  try {
    const result = await apiRequest(`/api/courses/${encodeURIComponent(state.session.course_id)}/quiz/record/`, {
      method: "POST",
      body: JSON.stringify({
        lecture_id: question.lecture_id,
        chunk_id: question.chunk_id,
        topic: question.topic,
        question: question.question,
        correct_answer: question.correct_answer,
        user_answer: answer,
      }),
    });
    await recordActivity("quiz_answered", { correct: result.correct, question_type: question.question_type });
    showFeedback(result, question);
    state.quizAskedQuestions.push(question.question);
    state.quizAsked += 1;
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

function showFeedback(result, question) {
  ui.feedbackHidden = false;
  byId("guided-session-feedback-result").textContent = result.correct
    ? "Correct!"
    : `Not quite — the correct answer is “${result.correct_answer}”.`;
  byId("guided-session-feedback-explanation").textContent = question.explanation || "";
  if (question.citation) {
    ui.feedbackSourceHidden = false;
    ui.feedbackSourceHref = question.citation.url || "#";
    ui.feedbackSourceTarget = question.citation.url ? "_blank" : "_self";
    byId("guided-session-feedback-source").textContent = `View source: ${question.citation.title}`;
  } else {
    ui.feedbackSourceHidden = true;
  }
  enforceUi();
}

async function nextQuestion() {
  const target = state.quizPhase === "multiple_choice" ? state.targets.mcTarget : state.targets.recallTarget;
  if (state.quizAsked >= target) {
    if (state.quizPhase === "multiple_choice") {
      ui.step = "guided-session-recall-prompt";
      enforceUi();
    } else {
      await finishSession();
    }
  } else {
    await loadNextQuestion();
  }
}

async function finishSession() {
  try {
    const result = await apiRequest(
      `/api/courses/${encodeURIComponent(state.session.course_id)}/study/sessions/${state.session.session_id}/complete/`,
      { method: "POST" },
    );
    showSummary(result.summary);
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

function showSummary(summary) {
  ui.step = "guided-session-summary-step";
  enforceUi();
  updateProgressLabel("Session complete");
  const list = byId("guided-session-summary-list");
  const accuracy = summary.questions_answered
    ? Math.round((summary.questions_correct / summary.questions_answered) * 100)
    : null;
  list.replaceChildren(
    Object.assign(document.createElement("li"), { textContent: `Flashcards reviewed: ${summary.flashcards_reviewed}` }),
    Object.assign(document.createElement("li"), { textContent: `Questions answered: ${summary.questions_answered}` }),
    Object.assign(document.createElement("li"), {
      textContent: accuracy === null ? "Accuracy: —" : `Accuracy: ${accuracy}%`,
    }),
  );
}

function resetToSetup() {
  state.session = null;
  Object.assign(ui, {
    setupHidden: false, loadingHidden: true, activeHidden: true, step: null,
    ratingsHidden: true, openAnswerHidden: true, feedbackHidden: true, feedbackSourceHidden: true,
  });
  enforceUi();
  clearAlert();
}

// Delegated from `document`, not bound to specific nodes: the shared DC
// shell can replace this whole static panel's DOM subtree at unpredictable
// points after load (see the `ui`/enforceUi comment above), which would
// silently detach any listener attached directly to a since-replaced
// element. A listener on `document` itself is never affected by that.
function bind() {
  document.addEventListener("submit", event => {
    if (event.target.id === "guided-session-setup") startSession(event);
  });
  document.addEventListener("click", event => {
    const target = event.target;
    if (target.closest("#guided-session-flashcard")) return flipFlashcard();
    const rating = target.closest("[data-rating]")?.dataset.rating;
    if (rating) return rateFlashcard(rating);
    if (target.closest("#guided-session-submit-open")) return submitAnswer(byId("guided-session-open-answer").value);
    if (target.closest("#guided-session-next-question")) return nextQuestion();
    if (target.closest("#guided-session-recall-yes")) return beginQuizPhase("open_ended");
    if (target.closest("#guided-session-recall-skip")) return finishSession();
    if (target.closest("#guided-session-restart")) return resetToSetup();
    if (target.closest("#guided-session-end-early")) return finishSession();
    if (target.closest("#study-subnav-progress, #study-subnav-flashcards, #study-subnav-quiz, #study-subnav-grades")) {
      ui.guidedRootHidden = true;
      enforceUi();
    }
    if (target.closest("#study-subnav-session")) {
      ui.guidedRootHidden = false;
      enforceUi();
    }
  });
}

if (guidedRoot) {
  bind();
  loadCourseOptions();
  resumeSession();
  enforceUi();
  // Re-assert this panel's intended visibility state on a short interval for
  // as long as the page is open. This is what makes the panel self-healing
  // against the shared DC shell's own occasional, unpredictable re-render of
  // this static subtree (see the `ui` comment above) — any reversion is
  // corrected on the next tick instead of leaving stale/overlapping steps
  // visible indefinitely.
  window.setInterval(enforceUi, 400);

  let courseOptionsAttempts = 0;
  const courseOptionsRetry = window.setInterval(() => {
    loadCourseOptions();
    if (++courseOptionsAttempts >= 3) window.clearInterval(courseOptionsRetry);
  }, 700);
}
