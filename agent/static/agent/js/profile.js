import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();
const $ = id => document.getElementById(id);
let profile = null;

function text(id, value) {
  if ($(id)) $(id).textContent = value;
}

function valueOrEmpty(value) {
  return value === null || value === undefined || value === "" ? "Not added" : String(value);
}

function fillValues(data) {
  document.querySelectorAll("[data-profile-value]").forEach(node => {
    node.textContent = valueOrEmpty(data[node.dataset.profileValue]);
  });
}

function renderCourses(courses) {
  const list = $("profile-course-list");
  list.replaceChildren();
  $("profile-courses-empty").hidden = courses.length > 0;
  list.hidden = courses.length === 0;
  courses.forEach(course => {
    const link = document.createElement("a");
    link.className = "profile-course-row";
    link.href = `/courses/${encodeURIComponent(course.id)}/`;
    const copy = document.createElement("span");
    const name = document.createElement("strong");
    const detail = document.createElement("small");
    name.textContent = course.name;
    detail.textContent = `${course.topics_count} ${course.topics_count === 1 ? "topic" : "topics"} · ${course.quizzes_completed} ${course.quizzes_completed === 1 ? "quiz" : "quizzes"}`;
    copy.append(name, detail);
    const progress = document.createElement("span");
    progress.className = "profile-course-progress";
    const progressLabel = document.createElement("b");
    progressLabel.textContent = course.mastery === null ? "Not measured" : `${course.mastery}% mastery`;
    const track = document.createElement("i");
    const bar = document.createElement("i");
    bar.style.width = `${Math.max(0, Math.min(100, course.mastery ?? 0))}%`;
    track.append(bar);
    progress.append(progressLabel, track);
    const arrow = document.createElement("b");
    arrow.className = "profile-course-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";
    link.append(copy, progress, arrow);
    list.append(link);
  });
}

function renderActivity(rows) {
  const list = $("profile-activity-list");
  list.replaceChildren();
  $("profile-activity-empty").hidden = rows.length > 0;
  list.hidden = rows.length === 0;
  const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  rows.forEach(row => {
    const item = document.createElement("li");
    const marker = document.createElement("span");
    marker.className = "profile-activity-marker";
    marker.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    title.textContent = row.title;
    detail.textContent = [row.course_name, row.topic, formatter.format(new Date(row.occurred_at))].filter(Boolean).join(" · ");
    copy.append(title, detail);
    item.append(marker, copy);
    list.append(item);
  });
}

function render(data) {
  profile = data;
  text("profile-name", data.display_name);
  text("profile-email", data.email);
  text("profile-bio", data.bio || (data.major ? `${data.major} student` : "Building a better semester with OnTrack."));
  text("profile-course-count", data.courses_enrolled);
  text("profile-streak", data.current_streak);
  text("academic-courses", data.courses_enrolled);
  text("academic-quizzes", data.quizzes_completed);
  const hasProgress = data.overall_progress !== null;
  $("profile-progress-stat").hidden = !hasProgress;
  $("academic-mastery-card").hidden = !hasProgress;
  if (hasProgress) {
    text("profile-progress", `${data.overall_progress}%`);
    text("academic-mastery", `${data.overall_progress}%`);
  }
  fillValues(data);
  const about = $("profile-about-text");
  about.textContent = data.bio || "Add a short bio to personalize your OnTrack profile.";
  $("profile-about-action").textContent = data.bio ? "Edit bio" : "Add bio";
  renderCourses(data.courses);
  renderActivity(data.recent_activity);
}

function activateTab(name, { focus = false, updateHash = false } = {}) {
  const tab = document.querySelector(`[data-profile-tab="${name}"]`) || document.querySelector("[data-profile-tab]");
  if (!tab) return;
  document.querySelectorAll("[data-profile-tab]").forEach(button => {
    const active = button === tab;
    button.setAttribute("aria-selected", String(active));
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-profile-panel]").forEach(panel => {
    panel.hidden = panel.dataset.profilePanel !== tab.dataset.profileTab;
  });
  if (focus) tab.focus();
  if (updateHash) history.replaceState(null, "", `#${tab.dataset.profileTab}`);
}

document.querySelectorAll("[data-profile-tab]").forEach((tab, index, tabs) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.profileTab, { updateHash: true }));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    activateTab(tabs[next].dataset.profileTab, { focus: true, updateHash: true });
  });
});

async function load() {
  $("profile-loading").hidden = false;
  $("profile-error").hidden = true;
  $("profile-content").hidden = true;
  try {
    render(await apiRequest("/api/profile/"));
    $("profile-loading").hidden = true;
    $("profile-content").hidden = false;
    activateTab(location.hash.slice(1) || "overview");
  } catch {
    $("profile-loading").hidden = true;
    $("profile-error").hidden = false;
  }
}

$("profile-retry")?.addEventListener("click", load);
load();
