import { initNavigation } from "./core/navigation.js";
import { apiRequest } from "./core/api.js";
import { focusFirst, restoreFocus } from "./core/modal.js";
import { showToast } from "./core/toast.js";

const page = document.querySelector("[data-page-section='courses']");
const byId = id => document.getElementById(id);
const state = { data: null, selected: null, returnFocus: null, menuButton: null, notificationOpen: false };

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("ot-icon"); svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use"); use.setAttribute("href", `#ot-icon-${name}`); svg.append(use);
  return svg;
}

function courseUrl(id, suffix = "") { return `${page.dataset.coursePageBase}${encodeURIComponent(id)}/${suffix}`; }
function apiUrl(id, suffix = "") { return `${page.dataset.courseApiBase}${encodeURIComponent(id)}/${suffix}`; }
function button(label, className = "courses-button") { const el = document.createElement("button"); el.type = "button"; el.className = className; el.textContent = label; return el; }

function setModal(backdrop, open, returnTo = null) {
  if (open) state.returnFocus = returnTo || document.activeElement;
  backdrop.hidden = !open; backdrop.setAttribute("aria-hidden", String(!open));
  document.body.classList.toggle("courses-modal-open", open);
  if (open) focusFirst(backdrop); else restoreFocus(state.returnFocus);
}

function setBusy(control, busy, busyLabel) {
  control.disabled = busy;
  if (busy) { control.dataset.label = control.textContent; control.textContent = busyLabel; }
  else if (control.dataset.label) { control.textContent = control.dataset.label; delete control.dataset.label; }
}

function syncUrl(semester, archived) {
  const url = new URL(window.location.href);
  if (semester) url.searchParams.set("semester", semester); else url.searchParams.delete("semester");
  if (archived) url.searchParams.set("archived", "1"); else url.searchParams.delete("archived");
  history.pushState({}, "", url);
}

function selectedQuery() {
  const params = new URLSearchParams(location.search);
  return { semester: params.get("semester") || "", archived: params.get("archived") === "1" };
}

function renderSemesterChoices(data) {
  const select = byId("courses-semester");
  select.replaceChildren(...data.semesters.map(term => {
    const option = document.createElement("option"); option.value = term.id; option.textContent = term.label; option.selected = term.id === data.semester.id; return option;
  }));
  byId("courses-semester-label").textContent = data.semester.label;
  const datalist = byId("course-semester-options");
  datalist.replaceChildren(...data.semesters.map(term => { const option = document.createElement("option"); option.value = term.id; option.label = term.label; return option; }));
}

function menuItem(label, action) {
  const item = button(label, "courses-menu-item"); item.dataset.courseAction = action; item.setAttribute("role", "menuitem"); return item;
}

function createCard(course) {
  const card = document.createElement("article"); card.className = "course-card course-overview-card"; card.dataset.courseId = course.id; card.style.setProperty("--course", course.color);
  const header = document.createElement("header"); header.className = "course-card-head";
  const badge = document.createElement("span"); badge.className = "course-badge"; badge.textContent = course.initials;
  const heading = document.createElement("div"); heading.className = "course-card-title";
  const title = document.createElement("a"); title.href = courseUrl(course.id); title.textContent = course.name;
  const code = document.createElement("span"); code.textContent = course.code || "Course code not added";
  const instructor = document.createElement("span"); instructor.className = "course-instructor"; instructor.style.color = course.color; instructor.textContent = course.instructor || "Instructor not added";
  heading.append(title, code, instructor);
  const menuWrap = document.createElement("div"); menuWrap.className = "courses-card-menu";
  const more = button("", "course-menu-trigger"); more.append(icon("more")); more.dataset.courseMenu = course.id; more.setAttribute("aria-label", `More actions for ${course.name}`); more.setAttribute("aria-expanded", "false");
  const menu = document.createElement("div"); menu.className = "course-menu courses-menu"; menu.hidden = true; menu.setAttribute("role", "menu");
  menu.append(menuItem("Open course", "open"), menuItem("Edit details", "edit"), menuItem(course.archived ? "Restore course" : "Archive course", "archive"), menuItem("Delete permanently", "delete"));
  menuWrap.append(more, menu); header.append(badge, heading, menuWrap);

  const deadline = document.createElement("section"); deadline.className = "course-deadline course-card-deadline";
  const deadlineIcon = document.createElement("span"); deadlineIcon.append(icon("calendar"));
  const deadlineCopy = document.createElement("div"); const label = document.createElement("span"); label.textContent = "Next deadline";
  if (course.next_deadline) {
    const link = document.createElement("a"); link.href = `/calendar/?view=week&date=${encodeURIComponent(course.next_deadline.date)}`; link.textContent = course.next_deadline.title;
    const meta = document.createElement("span"); meta.className = "course-deadline-meta"; meta.style.color = course.color; meta.textContent = `${course.next_deadline.date_label || course.next_deadline.date} · ${course.next_deadline.relative_label}`;
    deadlineCopy.append(label, link, meta);
  } else {
    const empty = document.createElement("strong"); empty.textContent = course.is_draft ? "Upload a syllabus to find deadlines" : "No confirmed future deadline"; deadlineCopy.append(label, empty);
  }
  deadline.append(deadlineIcon, deadlineCopy);

  const footer = document.createElement("footer"); footer.className = "course-card-footer";
  const materials = document.createElement("a"); materials.href = courseUrl(course.id, "materials/"); materials.className = "course-material-link course-material-count"; materials.append(icon("material"));
  const materialText = course.materials.count === null ? "Materials unavailable" : `${course.materials.count} ready material${course.materials.count === 1 ? "" : "s"}`;
  materials.append(document.createTextNode(materialText));
  if (course.materials.needs_review || course.materials.failed) materials.title = `${course.materials.needs_review} need review; ${course.materials.failed} failed`;
  const mastery = document.createElement("a"); mastery.href = `/study/?view=progress&course=${encodeURIComponent(course.id)}`; mastery.className = "course-mastery-link course-mastery";
  const masteryLabel = document.createElement("span"); masteryLabel.textContent = "Mastery";
  const progress = document.createElement("span"); progress.className = "course-progress course-mastery-track"; progress.setAttribute("role", "progressbar"); progress.setAttribute("aria-label", `Mastery for ${course.name}`);
  const score = course.mastery.score; progress.setAttribute("aria-valuemin", "0"); progress.setAttribute("aria-valuemax", "100");
  if (score !== null) progress.setAttribute("aria-valuenow", String(score));
  const fill = document.createElement("span"); fill.style.width = `${score || 0}%`; fill.style.background = course.color; progress.append(fill);
  const value = document.createElement("strong"); value.textContent = course.mastery.label; mastery.append(masteryLabel, progress, value);
  footer.append(materials, mastery); card.append(header, deadline, footer); card._course = course; return card;
}

function render(data) {
  state.data = data; renderSemesterChoices(data);
  byId("courses-active-count").textContent = data.summary.active_courses;
  byId("courses-deadline-count").textContent = data.summary.upcoming_deadlines;
  byId("courses-mastery-average").textContent = data.summary.average_mastery === null ? "—" : `${data.summary.average_mastery}%`;
  const archiveToggle = byId("courses-archive-toggle"); archiveToggle.querySelector("span").textContent = data.archived ? "Back to active courses" : "Archive courses";
  byId("courses-mode-heading").hidden = !data.archived;
  const warning = byId("courses-warning"); warning.hidden = !data.warnings.length; warning.textContent = data.warnings.map(item => item.detail).join(" ");
  const empty = byId("courses-empty"); empty.hidden = !!data.courses.length;
  byId("courses-empty-title").textContent = data.archived ? "No archived courses" : `No courses in ${data.semester.label}`;
  byId("courses-empty-copy").textContent = data.archived ? "Courses you archive will remain available here for restoration." : "Create a course to organize materials, deadlines, and study activity. You can upload a syllabus afterward.";
  empty.querySelector("[data-add-course]").hidden = data.archived;
  const grid = byId("courses-grid"); grid.replaceChildren(...data.courses.map(createCard));
  if (!data.archived && data.courses.length > 1) {
    const add = button("", "course-add-card"); add.dataset.addCourse = ""; const addIcon = document.createElement("span"); addIcon.append(icon("plus")); add.append(addIcon);
    const strong = document.createElement("strong"); strong.textContent = "Add another course"; const copy = document.createElement("small"); copy.textContent = "Create a course for this semester"; add.append(strong, copy); grid.append(add);
  }
  byId("courses-loading").hidden = true; byId("courses-error").hidden = true; byId("courses-content").hidden = false;
}

async function loadCourses() {
  byId("courses-loading").hidden = false; byId("courses-error").hidden = true; byId("courses-content").hidden = true;
  const query = selectedQuery(); const params = new URLSearchParams(); if (query.semester) params.set("semester", query.semester); if (query.archived) params.set("archived", "1");
  try { render(await apiRequest(`${page.dataset.overviewApi}?${params}`)); }
  catch (error) { byId("courses-loading").hidden = true; byId("courses-error").hidden = false; byId("courses-error-copy").textContent = ` ${error.message}`; }
}

function showSuccess(message, course = null) {
  const region = byId("courses-success"); region.replaceChildren(document.createTextNode(message));
  if (course) { const open = document.createElement("a"); open.href = courseUrl(course.id); open.textContent = "Open course"; const materials = document.createElement("a"); materials.href = courseUrl(course.id, "materials/"); materials.textContent = "Add materials"; region.append(" ", open, " · ", materials); }
  region.hidden = false;
}

function renderColors(selected) {
  byId("course-color-options").replaceChildren(...state.data.palette.map((color, index) => {
    const label = document.createElement("label"); label.className = "courses-color-choice"; label.style.setProperty("--choice", color); const input = document.createElement("input"); input.type = "radio"; input.name = "course-color"; input.value = color; input.checked = color === selected || (!selected && index === 0); input.setAttribute("aria-label", `Course color ${index + 1}`); label.append(input, document.createElement("span")); return label;
  }));
}

function openCourseForm(course = null, trigger = null) {
  state.selected = course; byId("course-form").reset(); byId("course-form-error").hidden = true;
  byId("course-form-title").textContent = course ? "Edit course" : "Add course"; byId("course-edit-id").value = course?.id || "";
  byId("course-id-field").hidden = !!course; byId("course-id").required = !course; byId("course-id").value = course?.id || "";
  byId("course-name").value = course?.name || ""; byId("course-code").value = course?.code || ""; byId("course-instructor").value = course?.instructor || "";
  byId("course-semester-input").value = course?.semester || state.data.semester.id; byId("course-semester-input").dataset.original = course?.semester || state.data.semester.id;
  byId("course-semester-confirm").hidden = true; renderColors(course?.color); setModal(byId("course-form-backdrop"), true, trigger);
}

async function saveCourse(event) {
  event.preventDefault(); const save = byId("course-save"); const editing = !!byId("course-edit-id").value; const id = editing ? byId("course-edit-id").value : byId("course-id").value.trim();
  const payload = { course_name: byId("course-name").value.trim(), course_code: byId("course-code").value.trim(), instructor: byId("course-instructor").value.trim(), semester: byId("course-semester-input").value.trim().toLowerCase(), color: document.querySelector("input[name='course-color']:checked")?.value };
  if (editing) payload.confirm_semester_move = byId("course-confirm-move").checked;
  setBusy(save, true, "Saving…"); byId("course-form-error").hidden = true;
  try {
    await apiRequest(apiUrl(id), { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) });
    setModal(byId("course-form-backdrop"), false); syncUrl(payload.semester, false); await loadCourses(); const course = state.data.courses.find(item => item.id === id); showSuccess(editing ? `${payload.course_name} was updated.` : `${payload.course_name} was created.`, course); showToast(editing ? "Course updated." : "Course created.", "success");
  } catch (error) {
    if (error.status === 409 && editing) { byId("course-semester-confirm").hidden = false; byId("course-confirm-move").focus(); }
    const detail = error.data && typeof error.data === "object" ? Object.values(error.data).flat().join(" ") : error.message; byId("course-form-error").textContent = detail; byId("course-form-error").hidden = false;
  } finally { setBusy(save, false); }
}

function openArchive(course, trigger) {
  state.selected = course; byId("course-archive-title").textContent = course.archived ? "Restore course?" : "Archive course?";
  byId("course-archive-copy").textContent = course.archived ? `Restore ${course.name} to ${course.semester_label}? It will return to active planning.` : `Archive ${course.name} from ${course.semester_label}? Its data will be preserved, but it will be excluded from Dashboard, Calendar, and reminder planning.`;
  byId("course-confirm-archive").textContent = course.archived ? "Restore course" : "Archive course"; setModal(byId("course-archive-backdrop"), true, trigger);
}

async function confirmArchive() {
  const control = byId("course-confirm-archive"); setBusy(control, true, state.selected.archived ? "Restoring…" : "Archiving…");
  try { await apiRequest(apiUrl(state.selected.id, "archive/"), { method: "PATCH", body: JSON.stringify({ archived: !state.selected.archived }) }); setModal(byId("course-archive-backdrop"), false); await loadCourses(); showSuccess(`${state.selected.name} was ${state.selected.archived ? "restored" : "archived"}.`); }
  catch (error) { showToast(error.message, "error"); } finally { setBusy(control, false); }
}

function openDelete(course, trigger) {
  state.selected = course; byId("course-delete-copy").textContent = `This permanently deletes ${course.name} and its stored course data. This cannot be undone.`; byId("course-delete-confirmation").value = ""; byId("course-delete-error").hidden = true; setModal(byId("course-delete-backdrop"), true, trigger);
}

async function confirmDelete() {
  if (byId("course-delete-confirmation").value !== state.selected.id) { byId("course-delete-error").textContent = `Type ${state.selected.id} exactly.`; byId("course-delete-error").hidden = false; return; }
  const control = byId("course-confirm-delete"); setBusy(control, true, "Deleting…");
  try { await apiRequest(apiUrl(state.selected.id), { method: "DELETE", body: JSON.stringify({ confirmation: state.selected.id }) }); setModal(byId("course-delete-backdrop"), false); await loadCourses(); showSuccess(`${state.selected.name} was permanently deleted.`); }
  catch (error) { byId("course-delete-error").textContent = error.message; byId("course-delete-error").hidden = false; } finally { setBusy(control, false); }
}

function closeMenus(restore = false) {
  document.querySelectorAll(".courses-menu:not([hidden])").forEach(menu => { menu.hidden = true; menu.previousElementSibling?.setAttribute("aria-expanded", "false"); });
  if (restore) restoreFocus(state.menuButton); state.menuButton = null;
}

async function loadNotifications() {
  const status = byId("courses-notification-status"), list = byId("courses-notification-list");
  try { const data = await apiRequest("/api/notifications/"); const count = data.unread_count || 0; const badge = byId("courses-notification-badge"); badge.textContent = count > 9 ? "9+" : String(count); badge.hidden = !count; status.textContent = data.notifications?.length ? `${count} unread update${count === 1 ? "" : "s"}` : "You’re all caught up."; list.replaceChildren(...(data.notifications || []).slice(0, 8).map(item => { const li = document.createElement("li"); const link = document.createElement("a"); link.href = item.action_url || "/dashboard/"; const strong = document.createElement("strong"); strong.textContent = item.title; const span = document.createElement("span"); span.textContent = item.body || item.message || "Course update"; link.append(strong, span); li.append(link); return li; })); }
  catch { status.textContent = "Notifications aren’t available right now."; }
}

function setNotifications(open, restore = true) {
  state.notificationOpen = open; const popover = byId("courses-notification-popover"), toggle = byId("courses-notification-toggle"); popover.hidden = !open; toggle.setAttribute("aria-expanded", String(open)); toggle.setAttribute("aria-label", open ? "Close notifications" : "Open notifications"); if (open) { loadNotifications(); focusFirst(popover); } else if (restore) toggle.focus();
}

function bind() {
  document.addEventListener("click", event => {
    const target = event.target;
    const add = target.closest("[data-add-course]"); if (add) return openCourseForm(null, add);
    if (target.closest("[data-close-course-form]")) return setModal(byId("course-form-backdrop"), false);
    if (target.closest("[data-cancel-archive]")) return setModal(byId("course-archive-backdrop"), false);
    if (target.closest("[data-cancel-delete]")) return setModal(byId("course-delete-backdrop"), false);
    const menuButton = target.closest("[data-course-menu]");
    if (menuButton) { const menu = menuButton.nextElementSibling, willOpen = menu.hidden; closeMenus(); menu.hidden = !willOpen; menuButton.setAttribute("aria-expanded", String(willOpen)); state.menuButton = menuButton; if (willOpen) focusFirst(menu); return; }
    const action = target.closest("[data-course-action]");
    if (action) { const card = action.closest(".course-overview-card"), course = card._course, trigger = state.menuButton; closeMenus(); if (action.dataset.courseAction === "open") location.assign(courseUrl(course.id)); else if (action.dataset.courseAction === "edit") openCourseForm(course, trigger); else if (action.dataset.courseAction === "archive") openArchive(course, trigger); else openDelete(course, trigger); return; }
    if (target.closest("#courses-notification-toggle")) return setNotifications(!state.notificationOpen);
    if (target.closest("[data-close-notifications]")) return setNotifications(false);
    if (state.notificationOpen && !target.closest(".courses-notifications")) setNotifications(false, false);
    if (!target.closest(".courses-card-menu")) closeMenus();
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!byId("course-form-backdrop").hidden) setModal(byId("course-form-backdrop"), false); else if (!byId("course-archive-backdrop").hidden) setModal(byId("course-archive-backdrop"), false); else if (!byId("course-delete-backdrop").hidden) setModal(byId("course-delete-backdrop"), false); else if (state.notificationOpen) setNotifications(false); else closeMenus(true);
  });
  ["course-form-backdrop", "course-archive-backdrop", "course-delete-backdrop"].forEach(id => byId(id).addEventListener("mousedown", event => { if (event.target === event.currentTarget) setModal(event.currentTarget, false); }));
  byId("course-form").addEventListener("submit", saveCourse); byId("course-confirm-archive").addEventListener("click", confirmArchive); byId("course-confirm-delete").addEventListener("click", confirmDelete);
  byId("course-semester-input").addEventListener("input", event => { byId("course-semester-confirm").hidden = !state.selected || event.target.value === event.target.dataset.original; if (byId("course-semester-confirm").hidden) byId("course-confirm-move").checked = false; });
  byId("courses-semester").addEventListener("change", event => { syncUrl(event.target.value, state.data.archived); loadCourses(); });
  byId("courses-archive-toggle").addEventListener("click", () => { syncUrl(state.data.semester.id, !state.data.archived); loadCourses(); });
  byId("courses-retry").addEventListener("click", loadCourses); window.addEventListener("popstate", loadCourses);
}

if (page) { initNavigation(); bind(); loadCourses(); loadNotifications(); }
