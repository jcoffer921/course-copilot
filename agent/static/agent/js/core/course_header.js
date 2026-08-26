import { apiRequest } from "./api.js";

// Shared, page-owned header controller for the Overview and Materials pages.
export function initCourseHeader(courseId) {
  const byId = id => document.getElementById(id);
  const formatDate = value => {
    if (!value) return "";
    const [year, month, day] = value.split("-").map(Number);
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(year, month - 1, day));
  };

  const ui = {
    loadingHidden: false,
    errorHidden: true,
    errorMessage: "",
    headerHidden: true,
    avatarColor: null,
    initials: "",
    name: courseId,
    instructor: "",
    deadlineTitle: "No upcoming deadlines",
    deadlineWhen: "",
    masteryPct: 0,
    masteryLabel: "Not enough data",
  };

  function enforceUi() {
    const set = (id, hidden) => { const el = byId(id); if (el) el.hidden = hidden; };
    set("course-header-loading", ui.loadingHidden);
    set("course-header-error", ui.errorHidden);
    set("course-header", ui.headerHidden);

    const error = byId("course-header-error");
    if (error) { const p = error.querySelector("p"); if (p) p.textContent = ui.errorMessage; }

    const avatar = byId("course-header-avatar");
    if (avatar) {
      avatar.textContent = ui.initials;
      if (ui.avatarColor) avatar.style.setProperty("--course", ui.avatarColor);
    }
    const name = byId("course-header-name");
    if (name) name.textContent = ui.name;
    const breadcrumb = byId("course-header-breadcrumb-name");
    if (breadcrumb) breadcrumb.textContent = ui.name;
    const instructor = byId("course-header-instructor");
    if (instructor) { instructor.hidden = !ui.instructor; const label = instructor.querySelector("span"); if (label) label.textContent = ui.instructor; }
    const deadlineTitle = byId("course-header-deadline-title");
    if (deadlineTitle) deadlineTitle.textContent = ui.deadlineTitle;
    const deadlineWhen = byId("course-header-deadline-when");
    if (deadlineWhen) deadlineWhen.textContent = ui.deadlineWhen;
    const masteryFill = byId("course-header-mastery-fill");
    if (masteryFill) masteryFill.style.width = `${ui.masteryPct}%`;
    const masteryProgress = byId("course-header-mastery-progress");
    if (masteryProgress) masteryProgress.setAttribute("aria-valuenow", String(ui.masteryPct));
    const masteryLabel = byId("course-header-mastery-label");
    if (masteryLabel) masteryLabel.textContent = ui.masteryLabel;
  }

  async function load() {
    ui.loadingHidden = false;
    ui.errorHidden = true;
    ui.headerHidden = true;
    enforceUi();
    try {
      const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/header/`);
      const course = data.course;
      ui.avatarColor = course.color;
      ui.initials = course.initials;
      ui.name = [course.code, course.name].filter(Boolean).join(" · ");
      ui.instructor = course.instructor;
      if (data.next_deadline) {
        const time = data.next_deadline.time ? `, ${data.next_deadline.time}` : "";
        ui.deadlineWhen = `${formatDate(data.next_deadline.date)}${time} (${data.next_deadline.relative_label})`;
        ui.deadlineTitle = data.next_deadline.title;
      } else {
        ui.deadlineTitle = "No upcoming deadlines";
        ui.deadlineWhen = "";
      }
      ui.masteryPct = data.mastery.available ? data.mastery.score : 0;
      ui.masteryLabel = data.mastery.label;
      ui.loadingHidden = true;
      ui.headerHidden = false;
    } catch (error) {
      ui.loadingHidden = true;
      ui.errorHidden = false;
      ui.errorMessage = error?.message || "Something went wrong.";
    }
    enforceUi();
  }

  enforceUi();
  load();

  return { refresh: load };
}
