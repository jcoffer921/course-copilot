import { initNavigation } from "./core/navigation.js";
import { apiRequest } from "./core/api.js";
import { focusFirst, restoreFocus } from "./core/modal.js";
import { showToast } from "./core/toast.js";
import { layoutOverlaps, visibilityForEvent } from "./calendar_layout.js";

initNavigation();

const root = document.querySelector(".cal-page");
if (!root) throw new Error("Calendar root is missing.");
const $ = (selector) => root.querySelector(selector);
const pad = (number) => String(number).padStart(2, "0");
const iso = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const parseDate = (value) => { const [y, m, d] = value.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (date, days) => { const next = new Date(date); next.setDate(next.getDate() + days); return next; };
const startOfWeek = (date) => addDays(date, -((date.getDay() + 6) % 7));
const startOfMonthGrid = (date) => addDays(new Date(date.getFullYear(), date.getMonth(), 1), -new Date(date.getFullYear(), date.getMonth(), 1).getDay());
const sameDay = (a, b) => iso(a) === iso(b);
const formatTime = (value) => value ? new Date(`2000-01-01T${value}`).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "All day";
const minutes = (value) => { const [h, m] = value.split(":").map(Number); return h * 60 + m; };
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

const params = new URLSearchParams(location.search);
const requestedDate = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "") ? parseDate(params.get("date")) : new Date();
const state = {
  anchor: requestedDate,
  miniMonth: new Date(requestedDate.getFullYear(), requestedDate.getMonth(), 1),
  view: params.get("view") === "month" ? "month" : "week",
  events: [], courses: [], typeGroups: [], warnings: [],
  courseFilters: new Set(), typeFilters: new Set(), showUnassigned: false,
  selectedEvent: null, returnFocus: null,
};

function updateUrl(replace = false) {
  const query = new URLSearchParams();
  query.set("view", state.view); query.set("date", iso(state.anchor));
  if (state.courseFilters.size !== state.courses.length) query.set("courses", [...state.courseFilters].join(","));
  if (state.typeFilters.size !== state.typeGroups.length) query.set("types", [...state.typeFilters].join(","));
  if (state.showUnassigned) query.set("unassigned", "1");
  history[replace ? "replaceState" : "pushState"]({}, "", `${location.pathname}?${query}`);
}

function filteredEvents() {
  const allowedTypes = new Set(state.typeGroups.filter((group) => state.typeFilters.has(group.id)).flatMap((group) => group.types));
  return state.events.filter((event) => {
    const courseOkay = event.course_id ? state.courseFilters.has(event.course_id) : state.showUnassigned;
    return courseOkay && allowedTypes.has(event.type);
  });
}

function visibleRange() {
  if (state.view === "week") { const start = startOfWeek(state.anchor); return [start, addDays(start, 6)]; }
  return [startOfMonthGrid(state.anchor), addDays(startOfMonthGrid(state.anchor), 41)];
}

function renderRange() {
  const [start, end] = visibleRange();
  $("#cal-range").textContent = state.view === "month"
    ? state.anchor.toLocaleDateString([], { month: "long", year: "numeric" })
    : `${start.toLocaleDateString([], { month: "short", day: "numeric" })} – ${end.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
  root.querySelectorAll("[data-cal-view]").forEach((button) => { const active = button.dataset.calView === state.view; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
}

function renderMiniCalendar() {
  $("#mini-month-title").textContent = state.miniMonth.toLocaleDateString([], { month: "long", year: "numeric" });
  const start = startOfMonthGrid(state.miniMonth); const grid = $("#mini-grid"); grid.replaceChildren();
  for (let i = 0; i < 42; i += 1) {
    const day = addDays(start, i); const button = document.createElement("button"); button.type = "button"; button.textContent = day.getDate();
    button.className = "cal-mini-day";
    if (day.getMonth() !== state.miniMonth.getMonth()) button.classList.add("outside");
    if (sameDay(day, new Date())) button.classList.add("today");
    if (sameDay(day, state.anchor)) button.classList.add("selected");
    button.setAttribute("aria-label", day.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" }));
    button.addEventListener("click", () => { state.anchor = day; state.miniMonth = new Date(day.getFullYear(), day.getMonth(), 1); updateUrl(); render(); });
    grid.append(button);
  }
}

function renderFilters() {
  const courses = $("#cal-course-filters"); courses.replaceChildren();
  state.courses.forEach((course) => {
    const label = document.createElement("label"); label.className = "cal-check-row";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(course.id)}" ${state.courseFilters.has(course.id) ? "checked" : ""}><span class="cal-filter-swatch" style="--course:${course.color}">${escapeHtml(course.id.toUpperCase().slice(0, 2))}</span><span>${escapeHtml(course.name)}</span>`;
    label.querySelector("input").addEventListener("change", (event) => { event.target.checked ? state.courseFilters.add(course.id) : state.courseFilters.delete(course.id); updateUrl(); render(); }); courses.append(label);
  });
  $("#cal-show-unassigned").checked = state.showUnassigned;
  const types = $("#cal-type-filters"); types.replaceChildren();
  state.typeGroups.forEach((group) => {
    const label = document.createElement("label"); label.className = "cal-check-row";
    const icon = group.id === "exams" ? "exam" : group.id === "study" ? "study" : group.id === "classes" ? "users" : "assignment";
    label.innerHTML = `<input type="checkbox" ${state.typeFilters.has(group.id) ? "checked" : ""}><svg class="cal-type-icon ot-icon" aria-hidden="true"><use href="#ot-icon-${icon}"></use></svg><span>${escapeHtml(group.label)}</span>`;
    label.querySelector("input").addEventListener("change", (event) => { event.target.checked ? state.typeFilters.add(group.id) : state.typeFilters.delete(group.id); updateUrl(); render(); }); types.append(label);
  });
}

function eventButton(event, className = "cal-event") {
  const button = document.createElement("button"); button.type = "button"; button.className = className; button.dataset.eventId = event.id; button.style.setProperty("--event", event.course_color); if (event.completed) button.classList.add("completed");
  button.innerHTML = `<span class="cal-event-time">${escapeHtml(event.all_day ? "" : formatTime(event.start_time))}</span><strong>${escapeHtml(event.title)}</strong><span>${escapeHtml(event.course_name)}</span>`;
  button.setAttribute("aria-label", `${event.title}, ${event.course_name}, ${event.all_day ? "all day" : formatTime(event.start_time)}`);
  button.addEventListener("click", (click) => openPopover(event, click.currentTarget)); return button;
}

function renderWeek(events) {
  const start = startOfWeek(state.anchor); const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const head = $("#cal-week-head"); head.replaceChildren(); head.append(Object.assign(document.createElement("div"), { className: "cal-corner" }));
  days.forEach((day) => { const cell = document.createElement("div"); cell.className = "cal-day-head" + (sameDay(day, new Date()) ? " today" : ""); cell.innerHTML = `<span>${day.toLocaleDateString([], { weekday: "short" })}</span><strong>${day.getDate()}</strong>`; head.append(cell); });
  const allDay = $("#cal-all-day"); allDay.replaceChildren(); const label = document.createElement("div"); label.className = "cal-all-day-label"; label.textContent = "All-day"; allDay.append(label);
  days.forEach((day) => { const lane = document.createElement("div"); lane.className = "cal-all-day-lane"; events.filter((event) => event.date === iso(day) && event.all_day).forEach((event) => lane.append(eventButton(event, "cal-all-day-event"))); allDay.append(lane); });
  const timed = events.filter((event) => !event.all_day && days.some((day) => event.date === iso(day)));
  const startHour = Math.min(8, ...timed.map((event) => Math.floor(minutes(event.start_time) / 60))); const endHour = Math.max(20, ...timed.map((event) => Math.ceil(minutes(event.end_time || event.start_time) / 60) + (event.end_time ? 0 : 1)));
  const grid = $("#cal-time-grid"); grid.replaceChildren(); grid.style.setProperty("--hours", endHour - startHour);
  const labels = document.createElement("div"); labels.className = "cal-time-labels"; for (let hour = startHour; hour <= endHour; hour += 1) { const span = document.createElement("span"); span.style.top = `${(hour - startHour) * 64}px`; span.textContent = new Date(2000, 0, 1, hour).toLocaleTimeString([], { hour: "numeric" }); labels.append(span); } grid.append(labels);
  const columns = document.createElement("div"); columns.className = "cal-day-columns"; grid.append(columns);
  days.forEach((day, index) => { const column = document.createElement("div"); column.className = "cal-day-column"; column.style.gridColumn = String(index + 1); columns.append(column);
    layoutOverlaps(timed.filter((event) => event.date === iso(day))).forEach((event) => { const button = eventButton(event); const top = (event._start - startHour * 60) / 60 * 64; const height = Math.max(34, (event._end - event._start) / 60 * 64); const width = 100 / event.overlapCount; button.style.top = `${top}px`; button.style.height = `${height}px`; button.style.left = `calc(${event.overlapColumn * width}% + 4px)`; button.style.width = `calc(${width}% - 7px)`; column.append(button); });
  });
  const now = new Date(); if (days.some((day) => sameDay(day, now)) && now.getHours() >= startHour && now.getHours() <= endHour) { const line = document.createElement("div"); line.className = "cal-now-line"; line.style.top = `${((now.getHours() * 60 + now.getMinutes()) - startHour * 60) / 60 * 64}px`; columns.append(line); }
}

function renderMonth(events) {
  const grid = $("#cal-month-grid"); grid.replaceChildren(); const start = startOfMonthGrid(state.anchor);
  for (let i = 0; i < 42; i += 1) { const day = addDays(start, i); const cell = document.createElement("div"); cell.className = "cal-month-day" + (day.getMonth() !== state.anchor.getMonth() ? " outside" : "") + (sameDay(day, new Date()) ? " today" : ""); cell.innerHTML = `<button type="button" class="cal-month-number" aria-label="Open week of ${day.toLocaleDateString()}">${day.getDate()}</button><div class="cal-month-events"></div>`; cell.querySelector(".cal-month-number").addEventListener("click", () => { state.anchor = day; state.view = "week"; updateUrl(); render(); });
    events.filter((event) => event.date === iso(day)).slice(0, 4).forEach((event) => cell.querySelector(".cal-month-events").append(eventButton(event, "cal-month-event"))); const count = events.filter((event) => event.date === iso(day)).length; if (count > 4) { const more = document.createElement("button"); more.className = "cal-more"; more.textContent = `+${count - 4} more`; more.addEventListener("click", () => { state.anchor = day; state.view = "week"; updateUrl(); render(); }); cell.append(more); } grid.append(cell); }
}

function renderUpcoming(events) {
  const list = $("#cal-upcoming-list"); list.replaceChildren(); const today = iso(new Date()); const upcoming = events.filter((event) => event.date >= today && ["hw", "project", "test_quiz"].includes(event.type)).slice(0, 3);
  if (!upcoming.length) { list.innerHTML = '<p class="cal-side-empty">No upcoming deadlines.</p>'; return; }
  upcoming.forEach((event) => { const button = document.createElement("button"); button.type = "button"; button.className = "cal-upcoming-row"; button.style.setProperty("--event", event.course_color); const when = parseDate(event.date); button.innerHTML = `<svg class="cal-upcoming-icon ot-icon" aria-hidden="true"><use href="#ot-icon-calendar"></use></svg><span><strong>${escapeHtml(event.title)}</strong><small>${escapeHtml(event.course_name)}</small></span><time>${when.toLocaleDateString([], { month: "short", day: "numeric" })}</time>`; button.addEventListener("click", () => { state.anchor = when; state.view = "week"; updateUrl(); render(); }); list.append(button); });
}

function render() {
  renderRange(); renderMiniCalendar(); renderFilters(); const events = filteredEvents(); const [start, end] = visibleRange(); const visible = events.filter((event) => event.date >= iso(start) && event.date <= iso(end));
  $("#cal-week").hidden = state.view !== "week"; $("#cal-month").hidden = state.view !== "month"; $("#cal-empty").hidden = visible.length > 0; if (state.view === "week") renderWeek(events); else renderMonth(events); renderUpcoming(events);
}

function openPopover(event, trigger) {
  state.selectedEvent = event; state.returnFocus = trigger; const popover = $("#cal-popover"); $("#cal-popover-title").textContent = event.title; $("#cal-popover-course").textContent = event.course_name; $("#cal-popover-dot").style.background = event.course_color;
  const date = parseDate(event.date).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" }); $("#cal-popover-details").innerHTML = `<div><dt>Date</dt><dd>${escapeHtml(date)}</dd></div><div><dt>Time</dt><dd>${escapeHtml(event.all_day ? "All day" : `${formatTime(event.start_time)}${event.end_time ? ` – ${formatTime(event.end_time)}` : ""}`)}</dd></div>${event.location ? `<div><dt>Location</dt><dd>${escapeHtml(event.location)}</dd></div>` : ""}`;
  $("#cal-popover-notes").textContent = event.notes || ""; $("#cal-popover-notes").hidden = !event.notes; $("#cal-delete").hidden = event.source === "syllabus"; $("#cal-complete").hidden = !["hw", "project", "test_quiz"].includes(event.type); $("#cal-complete").textContent = event.completed ? "Mark incomplete" : "Mark complete"; popover.hidden = false; const rect = trigger.getBoundingClientRect(); const width = 320; popover.style.left = `${Math.max(12, Math.min(innerWidth - width - 12, rect.left))}px`; popover.style.top = `${Math.min(innerHeight - popover.offsetHeight - 12, rect.bottom + 8)}px`; focusFirst(popover);
}
function closePopover() { $("#cal-popover").hidden = true; restoreFocus(state.returnFocus); }

function setModalOpen(modal, open) {
  modal.hidden = !open;
  modal.setAttribute("aria-hidden", String(!open));
  modal.style.display = open ? "grid" : "none";
}

function openEventModal(event = null) {
  closePopover(); state.returnFocus = document.activeElement; const form = $("#cal-event-form"); form.reset(); $("#cal-modal-title").textContent = event ? "Edit event" : "Add event"; $("#cal-event-id").value = event?.id || ""; $("#cal-event-key").value = event?.source === "syllabus" ? event.key : ""; $("#cal-event-title").value = event?.title || ""; $("#cal-event-date").value = event?.date || iso(state.anchor); $("#cal-event-course").value = event?.course_id || ""; $("#cal-event-all-day").checked = event ? event.all_day : false; $("#cal-event-start").value = event?.start_time || "09:00"; $("#cal-event-end").value = event?.end_time || "10:00"; $("#cal-event-type").value = event?.type || "other"; $("#cal-event-location").value = event?.location || ""; $("#cal-event-notes").value = event?.notes || ""; $("#cal-form-error").hidden = true;
  // Repeats: only offered when creating a brand-new event. Changing an
  // existing series' recurrence pattern isn't supported — delete and
  // recreate the series instead.
  $("#cal-repeat-fields").hidden = !!event; $("#cal-event-repeat").value = "none";
  $("#cal-repeat-weekdays").hidden = true; root.querySelectorAll("#cal-repeat-weekdays input").forEach((box) => { box.checked = false; });
  $("#cal-repeat-until-field").hidden = true; $("#cal-event-repeat-until").value = "";
  // Series scope: only offered when editing an event that's already part of a series.
  const hasSeries = !!event?.series_id;
  $("#cal-series-scope-field").hidden = !hasSeries;
  if (hasSeries) $('input[name="cal-series-scope"][value="this"]').checked = true;
  $("#cal-event-date").disabled = false;
  toggleTimeFields(); setModalOpen($("#cal-event-modal"), true); focusFirst($("#cal-event-modal"));
}
function closeEventModal() { setModalOpen($("#cal-event-modal"), false); restoreFocus(state.returnFocus); }
function toggleTimeFields() { $("#cal-time-fields").hidden = $("#cal-event-all-day").checked; }
function toggleRepeatFields() {
  const weekly = $("#cal-event-repeat").value === "weekly";
  $("#cal-repeat-weekdays").hidden = !weekly; $("#cal-repeat-until-field").hidden = !weekly;
  if (weekly && !$("#cal-event-repeat-until").value) {
    const start = parseDate($("#cal-event-date").value || iso(state.anchor));
    $("#cal-event-repeat-until").value = iso(addDays(start, 15 * 7 - 1));
  }
}
function toggleSeriesScopeDateField() {
  const scope = $('input[name="cal-series-scope"]:checked')?.value || "this";
  $("#cal-event-date").disabled = scope !== "this";
}

async function saveEvent(event) {
  event.preventDefault(); const id = $("#cal-event-id").value; const allDay = $("#cal-event-all-day").checked;
  const isNewEvent = !id; const repeating = isNewEvent && $("#cal-event-repeat").value === "weekly";
  $("#cal-save").disabled = true; $("#cal-form-error").hidden = true;
  try {
    let saved; let successMessage;
    if (repeating) {
      const weekdays = [...root.querySelectorAll("#cal-repeat-weekdays input:checked")].map((box) => box.value);
      if (!weekdays.length) throw new Error("Choose at least one day for the repeating event.");
      if (!$("#cal-event-repeat-until").value) throw new Error("Choose a repeat-until date.");
      const payload = {
        title: $("#cal-event-title").value.trim(), course_id: $("#cal-event-course").value || null,
        type: $("#cal-event-type").value, weekdays,
        start_date: $("#cal-event-date").value, end_date: $("#cal-event-repeat-until").value,
        time: allDay ? null : $("#cal-event-start").value || null, end_time: allDay ? null : $("#cal-event-end").value || null,
        location: $("#cal-event-location").value.trim(), notes: $("#cal-event-notes").value.trim(),
      };
      const result = await apiRequest(`${root.dataset.deadlinesApi}recurring/`, { method: "POST", body: JSON.stringify(payload) });
      saved = result.events[0]; successMessage = `${result.events.length} events added.`;
    } else {
      const payload = { title: $("#cal-event-title").value.trim(), date: $("#cal-event-date").value, course_id: $("#cal-event-course").value || null, type: $("#cal-event-type").value, time: allDay ? null : $("#cal-event-start").value || null, end_time: allDay ? null : $("#cal-event-end").value || null, location: $("#cal-event-location").value.trim(), notes: $("#cal-event-notes").value.trim() };
      if ($("#cal-event-key").value) payload.replaces_syllabus_key = $("#cal-event-key").value;
      if (!isNewEvent && !$("#cal-series-scope-field").hidden) payload.series_scope = $('input[name="cal-series-scope"]:checked')?.value || "this";
      saved = await apiRequest(id && !$("#cal-event-key").value ? `${root.dataset.deadlinesApi}${encodeURIComponent(id)}/` : root.dataset.deadlinesApi, { method: id && !$("#cal-event-key").value ? "PATCH" : "POST", body: JSON.stringify(payload) });
      successMessage = isNewEvent ? "Event added." : "Event updated.";
    }
    const visibility = visibilityForEvent(saved, state.typeGroups);
    state.anchor = parseDate(visibility.date);
    state.miniMonth = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1);
    if (visibility.courseId) state.courseFilters.add(visibility.courseId);
    if (visibility.showUnassigned) state.showUnassigned = true;
    if (visibility.typeGroupId) state.typeFilters.add(visibility.typeGroupId);
    updateUrl(true);
    closeEventModal(); showToast(successMessage, "success"); await loadCalendar();
  }
  catch (error) { $("#cal-form-error").textContent = error.message; $("#cal-form-error").hidden = false; }
  finally { $("#cal-save").disabled = false; }
}

async function deleteSelected() {
  if (!state.selectedEvent) return; $("#cal-confirm-delete").disabled = true;
  const options = { method: "DELETE" };
  if (!$("#cal-delete-series-scope-field").hidden) options.body = JSON.stringify({ series_scope: $('input[name="cal-delete-series-scope"]:checked')?.value || "this" });
  try {
    await apiRequest(`${root.dataset.deadlinesApi}${encodeURIComponent(state.selectedEvent.id)}/`, options);
    setModalOpen($("#cal-delete-modal"), false); closePopover(); showToast("Event deleted.", "success"); await loadCalendar();
  } catch (error) { showToast(error.message, "error"); } finally { $("#cal-confirm-delete").disabled = false; }
}

async function toggleCompleted() {
  const event = state.selectedEvent; if (!event) return; const completed = !event.completed; $("#cal-complete").disabled = true;
  try {
    if (event.source === "syllabus") {
      await apiRequest(root.dataset.deadlinesApi, { method: "POST", body: JSON.stringify({ course_id: event.course_id, date: event.date, time: event.start_time, end_time: event.end_time, title: event.title, type: event.type, completed, location: event.location || "", notes: event.notes || "", replaces_syllabus_key: event.key }) });
    } else {
      await apiRequest(`${root.dataset.deadlinesApi}${encodeURIComponent(event.id)}/`, { method: "PATCH", body: JSON.stringify({ completed }) });
    }
    closePopover(); showToast(completed ? "Event marked complete." : "Event marked incomplete.", "success"); await loadCalendar();
  } catch (error) { showToast(error.message, "error"); } finally { $("#cal-complete").disabled = false; }
}

async function loadCalendar() {
  $("#cal-loading").hidden = false; $("#cal-error").hidden = true; $("#cal-week").hidden = true; $("#cal-month").hidden = true;
  try { const data = await apiRequest(root.dataset.calendarApi); state.events = data.events || []; state.courses = data.courses || []; state.typeGroups = data.event_types || []; state.warnings = data.warnings || []; const currentParams = new URLSearchParams(location.search); const queryCourses = currentParams.get("courses"); const queryTypes = currentParams.get("types"); state.courseFilters = new Set(queryCourses ? queryCourses.split(",").filter((id) => state.courses.some((course) => course.id === id)) : state.courses.map((course) => course.id)); state.typeFilters = new Set(queryTypes ? queryTypes.split(",").filter((id) => state.typeGroups.some((group) => group.id === id)) : state.typeGroups.map((group) => group.id)); state.showUnassigned = currentParams.get("unassigned") === "1"; $("#cal-event-course").innerHTML = '<option value="">Unassigned</option>' + state.courses.map((course) => `<option value="${escapeHtml(course.id)}">${escapeHtml(course.name)}</option>`).join(""); $("#cal-warning").hidden = !state.warnings.length; $("#cal-warning").textContent = state.warnings.map((warning) => warning.detail).join(" "); render(); }
  catch (error) { $("#cal-error-message").textContent = error.message; $("#cal-error").hidden = false; }
  finally { $("#cal-loading").hidden = true; }
}

async function loadCalendarConnectionBanner() {
  try {
    const profile = await apiRequest("/api/profile/");
    $("#cal-reconnect-banner").hidden = !!profile.calendar_connected;
  } catch (error) { /* non-fatal — the banner just stays hidden */ }
}

$("#cal-today").addEventListener("click", () => { state.anchor = new Date(); state.miniMonth = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1); updateUrl(); render(); });
$("#cal-prev").addEventListener("click", () => { state.anchor = state.view === "week" ? addDays(state.anchor, -7) : new Date(state.anchor.getFullYear(), state.anchor.getMonth() - 1, 1); state.miniMonth = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1); updateUrl(); render(); });
$("#cal-next").addEventListener("click", () => { state.anchor = state.view === "week" ? addDays(state.anchor, 7) : new Date(state.anchor.getFullYear(), state.anchor.getMonth() + 1, 1); state.miniMonth = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1); updateUrl(); render(); });
$("#mini-prev").addEventListener("click", () => { state.miniMonth = new Date(state.miniMonth.getFullYear(), state.miniMonth.getMonth() - 1, 1); renderMiniCalendar(); }); $("#mini-next").addEventListener("click", () => { state.miniMonth = new Date(state.miniMonth.getFullYear(), state.miniMonth.getMonth() + 1, 1); renderMiniCalendar(); });
root.querySelectorAll("[data-cal-view]").forEach((button) => button.addEventListener("click", () => { state.view = button.dataset.calView; updateUrl(); render(); }));
$("#cal-show-unassigned").addEventListener("change", (event) => { state.showUnassigned = event.target.checked; updateUrl(); render(); }); $("#cal-add").addEventListener("click", () => openEventModal()); root.querySelector("[data-open-event]").addEventListener("click", () => openEventModal());
$("#cal-view-upcoming").addEventListener("click", () => { state.anchor = new Date(); state.view = "week"; state.courseFilters = new Set(state.courses.map((course) => course.id)); state.typeFilters = new Set(state.typeGroups.map((group) => group.id)); state.showUnassigned = true; updateUrl(); render(); });
$("#cal-filter-toggle").addEventListener("click", () => { const open = $("#cal-utility").classList.toggle("open"); $("#cal-filter-toggle").setAttribute("aria-expanded", String(open)); });
$("#cal-event-all-day").addEventListener("change", toggleTimeFields); $("#cal-event-repeat").addEventListener("change", toggleRepeatFields); root.querySelectorAll('input[name="cal-series-scope"]').forEach((radio) => radio.addEventListener("change", toggleSeriesScopeDateField)); $("#cal-event-form").addEventListener("submit", saveEvent); root.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", closeEventModal)); $(".cal-popover-close").addEventListener("click", closePopover); $("#cal-edit").addEventListener("click", () => openEventModal(state.selectedEvent)); $("#cal-delete").addEventListener("click", () => { const hasSeries = !!state.selectedEvent?.series_id; $("#cal-delete-series-scope-field").hidden = !hasSeries; if (hasSeries) $('input[name="cal-delete-series-scope"][value="this"]').checked = true; setModalOpen($("#cal-delete-modal"), true); focusFirst($("#cal-delete-modal")); }); $("[data-cancel-delete]").addEventListener("click", () => { setModalOpen($("#cal-delete-modal"), false); }); $("#cal-confirm-delete").addEventListener("click", deleteSelected); $("#cal-retry").addEventListener("click", loadCalendar);
$("#cal-complete").addEventListener("click", toggleCompleted);
document.addEventListener("pointerdown", (event) => {
  const popover = $("#cal-popover");
  if (popover.hidden || popover.contains(event.target)) return;
  closePopover();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") { if (!$("#cal-delete-modal").hidden) setModalOpen($("#cal-delete-modal"), false); else if (!$("#cal-event-modal").hidden) closeEventModal(); else if (!$("#cal-popover").hidden) closePopover(); return; }
  if (event.key !== "Tab") return;
  const modal = !$("#cal-delete-modal").hidden ? $("#cal-delete-modal") : !$("#cal-event-modal").hidden ? $("#cal-event-modal") : null;
  if (!modal) return;
  const focusable = [...modal.querySelectorAll("button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex='-1'])")].filter((element) => !element.hidden);
  if (!focusable.length) return; const first = focusable[0]; const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.addEventListener("popstate", () => location.reload());
setModalOpen($("#cal-event-modal"), false);
setModalOpen($("#cal-delete-modal"), false);
loadCalendar();
loadCalendarConnectionBanner();
