import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();
const byId = id => document.getElementById(id);
const root = document.querySelector("[data-page-section='study-dashboard']");
const state = { courses: [], course: null, recommendations: [], topics: [] };

function setUrl(push = false) {
  if (!state.course) return;
  const url = new URL(location.href); url.search = ""; url.searchParams.set("course", state.course.id);
  history[push ? "pushState" : "replaceState"]({}, "", url);
}

function destination(view, topic = "", resume = "") {
  if (view === "flashcards") return `/courses/${encodeURIComponent(state.course.id)}/study/flashcards/due/`;
  const params = new URLSearchParams({ course: state.course.id, view });
  if (topic) params.set("topic", topic);
  if (resume) params.set("resume", resume);
  return `/study/?${params}`;
}

const STEP_KIND = {
  flashcards: { label: "Flashcards", icon: "▤", color: "green" },
  quiz: { label: "Practice questions", icon: "?", color: "orange" },
  short: { label: "Short answer", icon: "✎", color: "amber" },
  recap: { label: "Session recap", icon: "⚑", color: "purple" },
};

function buildSteps(duration, rankedTopics) {
  const topicAt = index => rankedTopics[index] || rankedTopics[rankedTopics.length - 1] || "your weakest topics";
  if (duration <= 15) return [{ ...STEP_KIND.flashcards, detail: topicAt(0), minutes: duration }];
  if (duration <= 30) {
    const flashcardMinutes = Math.round(duration * 0.35);
    return [
      { ...STEP_KIND.flashcards, detail: topicAt(0), minutes: flashcardMinutes },
      { ...STEP_KIND.quiz, detail: topicAt(1), minutes: duration - flashcardMinutes },
    ];
  }
  const flashcardMinutes = Math.round(duration * 0.18);
  const quizMinutes = Math.round(duration * 0.44);
  const shortMinutes = Math.round(duration * 0.27);
  const recapMinutes = duration - flashcardMinutes - quizMinutes - shortMinutes;
  return [
    { ...STEP_KIND.flashcards, detail: topicAt(0), minutes: flashcardMinutes },
    { ...STEP_KIND.quiz, detail: topicAt(1), minutes: quizMinutes },
    { ...STEP_KIND.short, detail: topicAt(2), minutes: shortMinutes },
    { ...STEP_KIND.recap, detail: "Review progress and key takeaways", minutes: recapMinutes },
  ];
}

function renderSteps() {
  const duration = Number(byId("study-dash-duration").value);
  const ranked = state.recommendations.map(item => item.topic).filter((topic, index, all) => all.indexOf(topic) === index);
  const topics = ranked.length ? ranked : state.topics;
  const steps = buildSteps(duration, topics);
  byId("study-dash-steps").replaceChildren(...steps.map(step => {
    const li = document.createElement("li"); li.className = "study-dash-step";
    const icon = document.createElement("span"); icon.className = `study-dash-step-icon ${step.color}`; icon.textContent = step.icon; icon.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div"); copy.className = "study-dash-step-copy";
    const label = document.createElement("strong"); label.textContent = step.label;
    const detail = document.createElement("span"); detail.textContent = step.detail;
    copy.append(label, detail);
    const time = document.createElement("time"); time.textContent = `${step.minutes} min`;
    li.append(icon, copy, time);
    return li;
  }));
}

function renderDue(dueCards, weakCount, streak) {
  const rows = [
    { count: dueCards.length, label: "Flashcards", detail: dueCards.length ? "Ready for review" : "Nothing due right now", color: "green", href: state.topics.length ? destination("flashcards") : null },
    { count: weakCount, label: "Weak topics", detail: weakCount ? "Needs extra attention" : "Nothing flagged right now", color: "orange", href: `/courses/${encodeURIComponent(state.course.id)}/mastery/` },
    { count: streak, label: "Current streak", detail: streak ? "Keep it going!" : "Start today", color: "amber", href: "/dashboard/", suffix: streak === 1 ? "day" : "days" },
  ];
  byId("study-dash-due-list").replaceChildren(...rows.map(row => {
    const item = document.createElement(row.href ? "a" : "div"); item.className = "study-dash-stat-row";
    if (row.href) item.href = row.href;
    const iconWrap = document.createElement("span"); iconWrap.className = `study-dash-stat-icon ${row.color}`;
    const iconUse = row.label === "Flashcards" ? "material" : row.label === "Weak topics" ? "trend" : "flame";
    iconWrap.innerHTML = `<svg class="ot-icon" aria-hidden="true"><use href="#ot-icon-${iconUse}"/></svg>`;
    const number = document.createElement("strong"); number.className = "study-dash-stat-number";
    number.textContent = row.suffix ? `${row.count}` : String(row.count);
    if (row.suffix) { const suffixEl = document.createElement("span"); suffixEl.className = "study-dash-stat-suffix"; suffixEl.textContent = ` ${row.suffix}`; number.append(suffixEl); }
    const copy = document.createElement("div"); copy.className = "study-dash-stat-copy";
    const label = document.createElement("strong"); label.textContent = row.label;
    const detail = document.createElement("span"); detail.textContent = row.detail;
    copy.append(label, detail);
    item.append(iconWrap, number, copy);
    if (row.href) { const chevron = document.createElement("span"); chevron.className = "study-dash-stat-chevron"; chevron.setAttribute("aria-hidden", "true"); chevron.textContent = "›"; item.append(chevron); }
    return item;
  }));
}

function renderContinue(sessions) {
  const host = byId("study-dash-continue");
  const active = sessions.find(item => item.status === "in_progress");
  if (!active) { host.innerHTML = '<p class="learning-empty">No session in progress. Start one above to see it here.</p>'; return; }
  const row = document.createElement("div"); row.className = "study-dash-continue-row";
  const copy = document.createElement("div");
  const title = document.createElement("strong"); title.textContent = active.mode === "flashcards" ? "Flashcards" : active.mode === "quiz" ? "Practice questions" : "Mixed review";
  const topic = document.createElement("span"); topic.textContent = active.topic || "All topics";
  const meta = document.createElement("time"); meta.textContent = new Date(active.started_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  copy.append(title, topic, meta);
  const link = document.createElement("a"); link.className = "btn btn-secondary"; link.href = destination("session", active.topic, active.session_id); link.textContent = "Continue";
  row.append(copy, link); host.replaceChildren(row);
}

function masteryLabel(pct) {
  if (pct == null) return "Not enough data yet";
  if (pct >= 80) return "Great progress";
  if (pct >= 60) return "Good progress";
  if (pct >= 40) return "Keep practicing";
  return "Just getting started";
}

function renderFlashcards(dueCards, header) {
  const pct = header.mastery?.available ? Math.round(header.mastery.score) : null;
  byId("study-dash-fc-pct").textContent = pct == null ? "—" : `${pct}%`;
  byId("study-dash-fc-ring").style.setProperty("--progress", `${pct ?? 0}%`);
  byId("study-dash-fc-due").textContent = `${dueCards.length} card${dueCards.length === 1 ? "" : "s"} due`;
  byId("study-dash-fc-label").textContent = masteryLabel(pct);
  byId("study-dash-fc-link").href = destination("flashcards");
}

function quizNote(pct) {
  if (pct == null) return "Take a quiz to start tracking your accuracy.";
  if (pct >= 80) return "Great work! Keep it up.";
  if (pct >= 50) return "Good effort! Keep practicing.";
  return "Let's build this up — review before your next quiz.";
}

function renderQuizChart(points) {
  const host = byId("study-dash-quiz-chart");
  if (points.length < 2) { host.innerHTML = '<p class="study-dash-quiz-empty">Not enough quiz history yet for a trend.</p>'; return; }
  const width = 300, height = 88, padX = 8, padY = 10;
  const xStep = (width - padX * 2) / (points.length - 1);
  const coords = points.map((point, index) => ({ ...point, x: padX + index * xStep, y: padY + (1 - point.pct / 100) * (height - padY * 2) }));
  const linePath = coords.map((c, index) => `${index === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1].x.toFixed(1)},${height} L${coords[0].x.toFixed(1)},${height} Z`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height + 16}`);
  svg.setAttribute("class", "study-dash-sparkline");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Quiz accuracy trend across ${points.length} days, from ${Math.round(points[0].pct)}% to ${Math.round(points[points.length - 1].pct)}%`);

  const area = document.createElementNS(svg.namespaceURI, "path"); area.setAttribute("d", areaPath); area.setAttribute("class", "study-dash-spark-area");
  const line = document.createElementNS(svg.namespaceURI, "path"); line.setAttribute("d", linePath); line.setAttribute("class", "study-dash-spark-line");
  svg.append(area, line);

  coords.forEach(c => {
    const dot = document.createElementNS(svg.namespaceURI, "circle");
    dot.setAttribute("cx", String(c.x)); dot.setAttribute("cy", String(c.y)); dot.setAttribute("r", "3.2"); dot.setAttribute("class", "study-dash-spark-dot");
    const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = `${c.label}: ${Math.round(c.pct)}%`;
    dot.append(title); svg.append(dot);
  });

  [0, coords.length - 1].forEach(index => {
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", String(coords[index].x)); label.setAttribute("y", String(height + 13));
    label.setAttribute("text-anchor", index === 0 ? "start" : "end"); label.setAttribute("class", "study-dash-spark-axis");
    label.textContent = points[index].label; svg.append(label);
  });

  host.replaceChildren(svg);
}

function renderQuiz(attempts) {
  const recent = attempts.slice(0, 10);
  const pct = recent.length ? Math.round((recent.filter(a => a.correct).length / recent.length) * 100) : null;
  byId("study-dash-quiz-score").textContent = recent.length ? `${recent.filter(a => a.correct).length}/${recent.length}` : "—";
  byId("study-dash-quiz-note").textContent = quizNote(pct);
  byId("study-dash-quiz-link").href = destination("quiz");

  const byDay = new Map();
  [...attempts].reverse().forEach(attempt => {
    if (!attempt.timestamp) return;
    const day = attempt.timestamp.slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(attempt);
  });
  const points = [...byDay.entries()].slice(-8).map(([day, dayAttempts]) => {
    const [y, m, d] = day.split("-").map(Number);
    return { pct: (dayAttempts.filter(a => a.correct).length / dayAttempts.length) * 100, label: new Date(y, m - 1, d).toLocaleDateString([], { month: "short", day: "numeric" }) };
  });
  renderQuizChart(points);
}

function renderMastery(rows, topics) {
  const scored = new Map(rows.map(row => [row.topic, row]));
  const display = topics.slice(0, 5).map(topic => scored.get(topic) || { topic, score: null });
  const host = byId("study-dash-mastery-list");
  if (!display.length) { host.innerHTML = '<p class="learning-empty">Confirm course material to unlock mastery tracking.</p>'; byId("study-dash-mastery-link").href = `/courses/${encodeURIComponent(state.course.id)}/mastery/`; return; }
  host.replaceChildren(...display.map(row => {
    const pct = row.score == null ? null : Math.round(row.score * 100);
    const wrap = document.createElement("div"); wrap.className = "study-dash-mastery-row";
    const head = document.createElement("div"); head.className = "study-dash-mastery-row-head";
    const name = document.createElement("span"); name.textContent = row.topic;
    const value = document.createElement("span"); value.textContent = pct == null ? "—" : `${pct}%`;
    head.append(name, value);
    const bar = document.createElement("div"); bar.className = "topic-progress";
    bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", `${row.topic} mastery`);
    bar.setAttribute("aria-valuemin", "0"); bar.setAttribute("aria-valuemax", "100"); bar.setAttribute("aria-valuenow", String(pct ?? 0));
    const fill = document.createElement("i"); fill.style.width = `${pct ?? 0}%`; fill.style.background = pct != null && pct < 60 ? "#c67139" : "#4d7746";
    bar.append(fill); wrap.append(head, bar);
    return wrap;
  }));
  byId("study-dash-mastery-link").href = `/courses/${encodeURIComponent(state.course.id)}/mastery/`;
}

async function start(topic, duration, mode) {
  const feedback = byId("study-dash-feedback"); const button = document.querySelector(".study-dash-start");
  button.disabled = true; feedback.hidden = false; feedback.classList.remove("error"); feedback.textContent = "Starting your grounded study session…";
  try {
    const session = await apiRequest(`/api/courses/${encodeURIComponent(state.course.id)}/study/sessions/`, { method: "POST", body: JSON.stringify({ topic, duration_minutes: duration, mode }) });
    location.assign(destination("session", topic, session.session_id));
  } catch (error) {
    feedback.textContent = error.message || "Couldn't start a session — try again."; feedback.classList.add("error"); button.disabled = false;
  }
}

async function selectCourse(id, { push = true } = {}) {
  const course = state.courses.find(item => item.id === id); if (!course) return;
  state.course = course;
  byId("study-dash-course").value = course.id;
  setUrl(push);

  try {
    const [syllabus, recs, due, mastery, header, sessions, quizHistory, dashboard] = await Promise.all([
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/syllabus/`).catch(error => error.status === 404 ? { topics: [] } : Promise.reject(error)),
      apiRequest("/api/recommendations/?limit=50"),
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/flashcards/due/?limit=100`),
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/mastery/`),
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/header/`),
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/study/sessions/?limit=10`),
      apiRequest(`/api/courses/${encodeURIComponent(course.id)}/quiz/history/?limit=40`),
      apiRequest("/api/dashboard/"),
    ]);

    state.topics = syllabus.topics || [];
    state.recommendations = (recs.recommendations || []).filter(item => item.course_id === course.id);

    const topicSelect = byId("study-dash-topic"); topicSelect.replaceChildren();
    const recommendedOption = document.createElement("option"); recommendedOption.value = ""; recommendedOption.textContent = "Recommended"; topicSelect.append(recommendedOption);
    state.topics.forEach(topic => { const option = document.createElement("option"); option.value = topic; option.textContent = topic; topicSelect.append(option); });
    const requestedTopic = new URLSearchParams(location.search).get("topic");
    if (requestedTopic && state.topics.includes(requestedTopic)) topicSelect.value = requestedTopic;

    const weakCount = mastery.filter(row => ["needs_review", "at_risk"].includes(row.status)).length;
    renderSteps();
    renderDue(due.cards || [], weakCount, dashboard.streak || 0);
    renderContinue(sessions.sessions || []);
    renderFlashcards(due.cards || [], header);
    renderQuiz(quizHistory.attempts || []);
    renderMastery(mastery, state.topics);

    byId("study-dash-loading").hidden = true; byId("study-dash-error").hidden = true; byId("study-dash-content").hidden = false;
  } catch (error) {
    byId("study-dash-loading").hidden = true; byId("study-dash-error").hidden = false; byId("study-dash-error").querySelector("p").textContent = error.message;
  }
}

root?.addEventListener("submit", event => {
  if (event.target.id !== "study-dash-controls") return;
  event.preventDefault();
  const topic = byId("study-dash-topic").value || state.recommendations[0]?.topic || "";
  start(topic, Number(byId("study-dash-duration").value), byId("study-dash-mode").value);
});
byId("study-dash-duration")?.addEventListener("change", renderSteps);
byId("study-dash-course")?.addEventListener("change", event => selectCourse(event.target.value));
byId("study-dash-error")?.querySelector("button")?.addEventListener("click", () => selectCourse(state.course.id, { push: false }));
window.addEventListener("popstate", () => { const course = new URL(location.href).searchParams.get("course"); if (course) selectCourse(course, { push: false }).catch(() => {}); });

(async function init() {
  try {
    const payload = await apiRequest("/api/courses/overview/");
    const pages = await Promise.all((payload.semesters || []).filter(term => term.id !== payload.semester?.id).map(term => apiRequest(`/api/courses/overview/?semester=${encodeURIComponent(term.id)}`)));
    const byIdMap = new Map(); [payload, ...pages].flatMap(page => page.courses || []).filter(item => !item.archived).forEach(item => byIdMap.set(item.id, item));
    state.courses = [...byIdMap.values()];
    byId("study-dash-loading").hidden = true;
    if (!state.courses.length) { byId("study-dash-empty").hidden = false; return; }

    const select = byId("study-dash-course");
    state.courses.forEach(course => { const option = document.createElement("option"); option.value = course.id; option.textContent = course.name; select.append(option); });
    const requested = new URL(location.href).searchParams.get("course");
    const selected = state.courses.some(item => item.id === requested) ? requested : state.courses[0].id;
    await selectCourse(selected, { push: false });
  } catch (error) {
    byId("study-dash-loading").hidden = true; byId("study-dash-error").hidden = false; byId("study-dash-error").querySelector("p").textContent = error.message || "Study tools could not load.";
  }
})();
