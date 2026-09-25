import { apiRequest } from "./core/api.js";
import { confirmDialog } from "./core/dialogs.js?v=20260901-1";

const root = document.querySelector(".flash-session-page");
const courseId = root?.dataset.courseId;
const deckId = root?.dataset.deckId;
const requestedSessionId = new URLSearchParams(location.search).get("session");
const $ = id => document.getElementById(id);
let state = null;
let busy = false;

function alertMessage(message, error = false) {
  const element = $("fc-alert");
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle("is-error", error);
}

function announce(message) {
  $("fc-save-status").textContent = "";
  requestAnimationFrame(() => { $("fc-save-status").textContent = message; });
}

function setView(view) {
  ["loading", "error", "content"].forEach(name => { $("fc-" + name).hidden = name !== view; });
}

function errorText(error) {
  return error?.data?.detail || error?.message || "Something went wrong.";
}

function focusRow(item) {
  const row = document.createElement("div");
  const name = document.createElement("strong");
  const count = document.createElement("small");
  const track = document.createElement("span");
  const fill = document.createElement("i");
  row.className = "fc-focus-row";
  name.textContent = item.topic;
  count.textContent = `${item.reviewed}/${item.cards}`;
  fill.style.width = `${item.cards ? item.reviewed / item.cards * 100 : 0}%`;
  track.append(fill);
  row.append(name, count, track);
  return row;
}

function renderFocus() {
  const rows = (state.deck_focus || []).map(focusRow);
  $("fc-focus-list").replaceChildren(...rows);
  $("fc-topics-dialog-list").replaceChildren(...(state.deck_focus || []).map(focusRow));
  $("fc-view-topics").disabled = rows.length === 0;
}

function render() {
  setView("content");
  const complete = state.card_count ? Math.round(state.reviewed_count / state.card_count * 100) : 0;
  const successful = Object.values(state.ratings || {}).filter(value => value === "good" || value === "easy").length;
  const needsReview = Object.values(state.ratings || {}).filter(value => value === "again" || value === "hard").length;
  $("fc-course").textContent = state.course_name;
  $("fc-title").textContent = state.title || "Flashcards";
  $("fc-due").textContent = `${state.card_count} cards due`;
  $("fc-progress").style.width = `${complete}%`;
  $("fc-progress").parentElement.setAttribute("aria-valuenow", String(complete));
  $("fc-percent").textContent = `${complete}%`;
  $("fc-summary-ring").style.setProperty("--progress", `${complete * 3.6}deg`);
  $("fc-reviewed").textContent = state.reviewed_count;
  $("fc-remaining").textContent = Math.max(0, state.card_count - state.reviewed_count);
  $("fc-review-again").textContent = needsReview;
  $("fc-success").lastChild.textContent = `${successful} successful`;
  $("fc-focus").textContent = state.title || "Due course topics";
  renderFocus();

  const card = state.current_card;
  if (!card) {
    $("fc-card-meta").textContent = "Deck complete";
    $("fc-term").textContent = state.card_count ? "You reviewed every card in this deck." : "No flashcards are due right now.";
    $("fc-topic").textContent = "";
    $("fc-side").textContent = "Complete";
    $("fc-hint").textContent = "Come back when more cards are due.";
    $("fc-card").disabled = true;
    $("fc-prev").disabled = true;
    $("fc-next").disabled = true;
    $("fc-ratings").querySelectorAll("button").forEach(button => { button.disabled = true; });
    $("fc-rating-help").textContent = state.card_count ? "Session complete." : "Your due queue is clear.";
    return;
  }

  $("fc-card").disabled = busy || state.status !== "in_progress";
  $("fc-card").setAttribute("aria-pressed", String(state.revealed));
  $("fc-card-meta").textContent = `Card ${state.position + 1} of ${state.card_count}`;
  $("fc-topic").textContent = card.topic || "Course review";
  $("fc-side").textContent = state.revealed ? "Back" : "Front";
  $("fc-term").textContent = state.revealed ? card.definition : card.term;
  $("fc-hint").textContent = state.revealed ? "Rate how well you recalled this card" : "Click the card or press Space to reveal the answer";
  $("fc-source").textContent = card.source_label || "Source unavailable for this saved card";
  $("fc-prev").disabled = busy || state.position === 0;
  $("fc-next").disabled = busy || state.position >= state.card_count - 1;
  $("fc-ratings").querySelectorAll("button").forEach(button => { button.disabled = busy || !state.revealed || state.status !== "in_progress"; });
  $("fc-rating-help").textContent = state.revealed ? "Choose a rating to update your review schedule." : "Reveal the card to rate your confidence.";
}

async function create() {
  setView("loading");
  try {
    if (requestedSessionId) {
      state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/flashcards/sessions/${encodeURIComponent(requestedSessionId)}/`);
    } else {
      state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/flashcards/${encodeURIComponent(deckId)}/sessions/`, { method: "POST" });
      const url = new URL(location.href);
      url.searchParams.set("session", state.session_id);
      history.replaceState({}, "", url);
    }
    render();
  } catch (error) {
    setView("error");
    $("fc-error").querySelector("p").textContent = errorText(error);
  }
}

async function action(path, body, successMessage = "") {
  if (busy || !state) return false;
  busy = true;
  try {
    state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/flashcards/sessions/${state.session_id}/${path}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    alertMessage("");
    if (successMessage) announce(successMessage);
    return true;
  } catch (error) {
    alertMessage(errorText(error), true);
    return false;
  } finally {
    busy = false;
    render();
  }
}

async function navigate(position) {
  if (busy || !state?.current_card || position < 0 || position >= state.card_count) return;
  busy = true;
  try {
    state = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/study/flashcards/sessions/${state.session_id}/`, {
      method: "PATCH",
      body: JSON.stringify({ position }),
    });
    alertMessage("");
  } catch (error) {
    alertMessage(errorText(error), true);
  } finally {
    busy = false;
    render();
  }
}

async function endSession() {
  const remaining = Math.max(0, state.card_count - state.reviewed_count);
  if (remaining && !(await confirmDialog({ title: "End flashcard session?", message: `${remaining} card${remaining === 1 ? " is" : "s are"} still remaining. Completed reviews will be kept.`, confirmLabel: "End session" }))) return;
  if (await action("end/", undefined, "Flashcard session ended.")) {
    location.assign(`/courses/${encodeURIComponent(courseId)}/study/`);
  }
}

$("fc-card")?.addEventListener("click", () => state?.current_card && action("reveal/", undefined, state.revealed ? "Answer hidden." : "Answer revealed."));
$("fc-prev")?.addEventListener("click", () => navigate(state.position - 1));
$("fc-next")?.addEventListener("click", () => navigate(state.position + 1));
$("fc-end")?.addEventListener("click", endSession);
$("fc-retry")?.addEventListener("click", create);
$("fc-ratings")?.addEventListener("click", event => {
  const rating = event.target.closest("button")?.dataset.rating;
  if (rating && state.current_card) action("rate/", { card_key: state.current_card.key, rating }, `Card rated ${rating}. Review schedule updated.`);
});
$("fc-view-topics")?.addEventListener("click", () => $("fc-topics-dialog").showModal());
$("fc-topics-close")?.addEventListener("click", () => $("fc-topics-dialog").close());
$("fc-topics-dialog")?.addEventListener("click", event => { if (event.target === $("fc-topics-dialog")) $("fc-topics-dialog").close(); });
document.addEventListener("keydown", event => {
  if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(event.target.tagName)) return;
  if (!state) return;
  if (event.code === "Space" || event.key.toLowerCase() === "r") {
    event.preventDefault();
    if (state?.current_card) action("reveal/", undefined, state.revealed ? "Answer hidden." : "Answer revealed.");
  }
  if (event.key === "ArrowLeft") navigate(state.position - 1);
  if (event.key === "ArrowRight") navigate(state.position + 1);
});

create();
