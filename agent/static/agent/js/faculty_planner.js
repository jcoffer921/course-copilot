import { apiRequest } from "./core/api.js";
import { getCsrfToken } from "./core/csrf.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();

const root = document.querySelector(".faculty-planner-page");
const byId = id => document.getElementById(id);
const initialData = JSON.parse(byId("faculty-program-requirements")?.textContent || "[]");
let programs = initialData;
let reviewRequirements = null;
let reviewSourceFilename = "";
let selectedProgram = null;
let currentDraft = null;

function errorMessage(error) {
  if (typeof error?.data?.detail === "string") return error.data.detail;
  if (error?.data && typeof error.data === "object") {
    const message = Object.values(error.data).flat().find(value => typeof value === "string");
    if (message) return message;
  }
  return error?.message || "Something went wrong.";
}

function showAlert(message, isError = false) {
  const alert = byId("faculty-planner-alert");
  alert.textContent = message;
  alert.classList.toggle("error", isError);
  alert.hidden = false;
}

function clearAlert() {
  byId("faculty-planner-alert").hidden = true;
}

function setBusy(form, busy, label) {
  const button = form.querySelector("button[type='submit']");
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.defaultLabel;
}

function textNode(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function renderLibrary() {
  const list = byId("program-library-list");
  list.replaceChildren();
  byId("program-library-empty").hidden = programs.length > 0;
  programs.forEach(program => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "faculty-program-row";
    button.dataset.requirementId = program.requirement_id;
    const identity = document.createElement("span");
    identity.append(textNode("strong", program.program_name), textNode("small", program.catalog_year));
    const updated = program.updated_at ? new Date(program.updated_at).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }) : "Confirmed";
    button.append(identity, textNode("span", `Updated ${updated}`, "faculty-program-updated"), textNode("span", "Plan →", "faculty-program-action"));
    button.addEventListener("click", () => selectProgram(program));
    list.append(button);
  });
}

function input(value, field, options = {}) {
  const control = document.createElement(options.multiline ? "textarea" : "input");
  control.className = "input";
  control.dataset.field = field;
  control.value = value ?? "";
  if (options.type) control.type = options.type;
  if (options.min !== undefined) control.min = options.min;
  if (options.step) control.step = options.step;
  if (options.placeholder) control.placeholder = options.placeholder;
  return control;
}

function renderReview() {
  byId("review-program-name").value = reviewRequirements.program_name || "";
  byId("review-catalog-year").value = reviewRequirements.catalog_year || "";
  byId("review-total-credits").value = reviewRequirements.total_credits_required ?? 0;
  byId("requirements-source-name").textContent = reviewSourceFilename;
  byId("overwrite-warning").hidden = true;

  const categories = byId("requirements-categories");
  categories.replaceChildren();
  (reviewRequirements.categories || []).forEach((category, categoryIndex) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "review-group review-dates-group faculty-category";
    fieldset.dataset.categoryIndex = categoryIndex;

    const header = document.createElement("div");
    header.className = "faculty-category-header";
    const nameControl = input(category.name, "category-name", { placeholder: "Category name" });
    nameControl.setAttribute("aria-label", "Category name");
    const creditsControl = input(category.credits_required, "category-credits", { type: "number", min: "0", step: "0.5" });
    creditsControl.setAttribute("aria-label", "Category credits required");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "faculty-remove-button";
    remove.textContent = "Remove category";
    remove.addEventListener("click", () => {
      reviewRequirements = collectReview();
      reviewRequirements.categories.splice(categoryIndex, 1);
      renderReview();
    });
    header.append(nameControl, creditsControl, remove);
    fieldset.append(header);

    const head = document.createElement("div");
    head.className = "faculty-course-head";
    ["Code", "Title", "Credits", "Prerequisites", "Notes", ""].forEach(label => head.append(textNode("span", label)));
    fieldset.append(head);

    const courseList = document.createElement("div");
    courseList.className = "faculty-course-list";
    (category.courses || []).forEach((course, courseIndex) => {
      const row = document.createElement("div");
      row.className = "review-row faculty-course-row";
      row.append(
        input(course.code, "code", { placeholder: "CS 101" }),
        input(course.title, "title", { placeholder: "Course title" }),
        input(course.credits, "credits", { type: "number", min: "0", step: "0.5" }),
        input((course.prerequisites || []).join(", "), "prerequisites", { placeholder: "Comma separated" }),
        input(course.notes, "notes", { placeholder: "Notes" })
      );
      const removeCourse = document.createElement("button");
      removeCourse.type = "button";
      removeCourse.className = "faculty-remove-button";
      removeCourse.textContent = "Remove";
      removeCourse.addEventListener("click", () => {
        reviewRequirements = collectReview();
        reviewRequirements.categories[categoryIndex].courses.splice(courseIndex, 1);
        renderReview();
      });
      row.append(removeCourse);
      courseList.append(row);
    });
    fieldset.append(courseList);

    const addCourse = document.createElement("button");
    addCourse.type = "button";
    addCourse.className = "review-add-item";
    addCourse.textContent = "＋ Add course";
    addCourse.addEventListener("click", () => {
      reviewRequirements = collectReview();
      reviewRequirements.categories[categoryIndex].courses.push({ code: "", title: "", credits: 0, prerequisites: [], notes: "" });
      renderReview();
    });
    fieldset.append(addCourse);
    categories.append(fieldset);
  });
  byId("requirements-review").hidden = false;
  byId("faculty-planning-state").hidden = true;
}

function collectReview() {
  return {
    program_name: byId("review-program-name").value.trim(),
    catalog_year: byId("review-catalog-year").value.trim(),
    total_credits_required: Number(byId("review-total-credits").value) || 0,
    categories: [...document.querySelectorAll(".faculty-category")].map(category => ({
      name: category.querySelector("[data-field='category-name']").value.trim(),
      credits_required: Number(category.querySelector("[data-field='category-credits']").value) || 0,
      courses: [...category.querySelectorAll(".faculty-course-row")].map(row => ({
        code: row.querySelector("[data-field='code']").value.trim(),
        title: row.querySelector("[data-field='title']").value.trim(),
        credits: Number(row.querySelector("[data-field='credits']").value) || 0,
        prerequisites: row.querySelector("[data-field='prerequisites']").value.split(",").map(value => value.trim()).filter(Boolean),
        notes: row.querySelector("[data-field='notes']").value.trim(),
      })),
    })),
  };
}

function upsertProgram(program) {
  const index = programs.findIndex(item => item.requirement_id === program.requirement_id);
  if (index >= 0) programs[index] = program;
  else programs.push(program);
  programs.sort((left, right) => `${left.program_name}${left.catalog_year}`.localeCompare(`${right.program_name}${right.catalog_year}`));
  renderLibrary();
}

async function confirmRequirements(overwrite = false) {
  reviewRequirements = collectReview();
  const data = await apiRequest(root.dataset.confirmUrl, {
    method: "POST",
    body: JSON.stringify({ confirm: true, requirements: reviewRequirements, source_filename: reviewSourceFilename, overwrite }),
  });
  upsertProgram(data.program_requirement);
  byId("requirements-review").hidden = true;
  showAlert(overwrite ? "Confirmed requirements were updated." : "Program requirements confirmed.");
  selectProgram(data.program_requirement);
}

function appendMessage(role, content) {
  const message = document.createElement("div");
  message.className = `faculty-chat-message faculty-chat-message-${role}`;
  message.append(textNode("span", role === "assistant" ? "Cora" : "You"), textNode("p", content));
  byId("faculty-chat-messages").append(message);
  message.scrollIntoView({ block: "nearest" });
}

function renderDraft(draft) {
  currentDraft = draft;
  byId("download-plan").disabled = !draft;
  byId("draft-plan-empty").hidden = Boolean(draft);
  const preview = byId("draft-plan-preview");
  preview.hidden = !draft;
  preview.replaceChildren();
  if (!draft) return;

  preview.append(textNode("h3", draft.student_major || "Academic plan"));
  (draft.semesters || []).forEach(semester => {
    const section = document.createElement("section");
    section.className = "faculty-draft-semester";
    section.append(textNode("h4", semester.label || "Semester"));
    const list = document.createElement("ul");
    (semester.courses || []).forEach(course => {
      const item = document.createElement("li");
      item.append(textNode("strong", course.code || ""), textNode("span", course.title || ""), textNode("small", `${course.credits ?? 0} credits`));
      list.append(item);
    });
    section.append(list);
    preview.append(section);
  });
  preview.append(textNode("p", `Total planned credits: ${draft.total_credits ?? 0}`, "faculty-draft-total"));
  if (draft.notes) preview.append(textNode("p", draft.notes, "faculty-draft-notes"));
}

function selectProgram(program) {
  const changedProgram = selectedProgram?.requirement_id !== program.requirement_id;
  selectedProgram = program;
  byId("selected-program-label").textContent = `${program.program_name} · ${program.catalog_year}`;
  byId("requirements-review").hidden = true;
  byId("faculty-planning-state").hidden = false;
  byId("faculty-chat-messages").replaceChildren();
  appendMessage("assistant", "Tell me the student's intended major, completed coursework, and any scheduling constraints. I’ll ask for anything else needed before drafting a plan.");
  renderDraft(null);
  if (changedProgram) apiRequest(root.dataset.resetUrl, { method: "POST" }).catch(() => {});
  byId("faculty-chat-input").focus();
}

byId("requirements-upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  clearAlert();
  const form = event.currentTarget;
  setBusy(form, true, "Extracting…");
  try {
    const data = await apiRequest(root.dataset.importUrl, { method: "POST", body: new FormData(form) });
    reviewRequirements = data.requirements;
    reviewSourceFilename = data.source_filename || form.elements.file.files[0]?.name || "";
    renderReview();
  } catch (error) {
    showAlert(errorMessage(error), true);
  } finally {
    setBusy(form, false);
  }
});

byId("requirements-review-form").addEventListener("submit", async event => {
  event.preventDefault();
  clearAlert();
  setBusy(event.currentTarget, true, "Confirming…");
  try {
    await confirmRequirements(false);
  } catch (error) {
    if (error.status === 409 && error.data?.existing) {
      const existing = error.data.existing;
      byId("overwrite-summary").textContent = `${existing.program_name} (${existing.catalog_year}) has ${existing.course_count} courses across ${existing.category_count} categories. It was last updated ${new Date(existing.updated_at).toLocaleString()}.`;
      byId("overwrite-warning").hidden = false;
    } else {
      showAlert(errorMessage(error), true);
    }
  } finally {
    setBusy(event.currentTarget, false);
  }
});

byId("overwrite-requirements").addEventListener("click", async event => {
  event.currentTarget.disabled = true;
  try {
    await confirmRequirements(true);
  } catch (error) {
    showAlert(errorMessage(error), true);
  } finally {
    event.currentTarget.disabled = false;
  }
});

byId("add-requirement-category").addEventListener("click", () => {
  reviewRequirements = collectReview();
  reviewRequirements.categories.push({ name: "", credits_required: 0, courses: [] });
  renderReview();
});

byId("cancel-requirements-review").addEventListener("click", () => {
  reviewRequirements = null;
  byId("requirements-review").hidden = true;
});

byId("faculty-chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedProgram) return;
  const inputControl = byId("faculty-chat-input");
  const message = inputControl.value.trim();
  if (!message) return;
  inputControl.value = "";
  appendMessage("user", message);
  setBusy(event.currentTarget, true, "Thinking…");
  try {
    const data = await apiRequest(root.dataset.chatUrl, {
      method: "POST",
      body: JSON.stringify({ program_requirement_id: selectedProgram.requirement_id, message }),
    });
    appendMessage("assistant", data.reply);
    if (data.draft_plan) renderDraft(data.draft_plan);
  } catch (error) {
    showAlert(errorMessage(error), true);
    inputControl.value = message;
  } finally {
    setBusy(event.currentTarget, false);
    inputControl.focus();
  }
});

byId("new-student").addEventListener("click", async () => {
  try {
    await apiRequest(root.dataset.resetUrl, { method: "POST" });
    byId("faculty-chat-messages").replaceChildren();
    appendMessage("assistant", "Ready for a new student. Share their intended major, completed coursework, and scheduling constraints.");
    renderDraft(null);
    showAlert("The previous student's session details were cleared.");
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
});

byId("download-plan").addEventListener("click", async event => {
  if (!currentDraft) return;
  event.currentTarget.disabled = true;
  try {
    const response = await fetch(root.dataset.exportUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": getCsrfToken(), "Accept": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
    });
    if (!response.ok) {
      const data = (response.headers.get("content-type") || "").includes("application/json") ? await response.json() : null;
      throw new Error(data?.detail || `Download failed with status ${response.status}.`);
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    const disposition = response.headers.get("content-disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
    link.download = filename || "academic-plan.docx";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    showAlert(errorMessage(error), true);
  } finally {
    event.currentTarget.disabled = false;
  }
});

const uploadInput = byId("requirements-upload-form").elements.file;
const dropzone = uploadInput.closest(".materials-dropzone");
uploadInput.addEventListener("change", () => {
  document.querySelector(".materials-dropzone-filename").textContent = uploadInput.files[0]?.name || "";
});
["dragenter", "dragover"].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.add("materials-dropzone-active");
}));
["dragleave", "drop"].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.remove("materials-dropzone-active");
}));
dropzone.addEventListener("drop", event => {
  const workbook = [...event.dataTransfer.files].find(file => file.name.toLowerCase().endsWith(".xlsx"));
  if (!workbook) {
    showAlert("Choose an XLSX workbook.", true);
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(workbook);
  uploadInput.files = transfer.files;
  uploadInput.dispatchEvent(new Event("change"));
});

renderLibrary();
