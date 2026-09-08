import { initNavigation } from "./core/navigation.js";
import { initCourseHeader } from "./core/course_header.js";
import { apiRequest } from "./core/api.js";
import "./core/modal.js";
import "./core/toast.js";
import { confirmDialog, promptDialog } from "./core/dialogs.js?v=20260901-1";
initNavigation();

const root = document.querySelector("[data-page-section='materials']");
const courseId = root?.dataset.courseId;
let reviewMaterialId = null;
let reviewCandidate = null;
let pollTimer = null;
let courseHeader = null;
let openMenuTrigger = null;

const byId = id => document.getElementById(id);
const text = (tag, value, className) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
};

function errorMessage(error) {
  if (error?.data && typeof error.data === "object") {
    // `detail` is the human-readable message on {code, detail, material}
    // MaterialProcessingError responses — check it before the generic
    // field-error flattening below, which would otherwise return the
    // machine-readable `code` first purely because it happens to sort
    // ahead of `detail` in object key order.
    if (typeof error.data.detail === "string") return error.data.detail;
    const fieldMessage = Object.values(error.data).flat().find(value => typeof value === "string");
    if (fieldMessage) return fieldMessage;
  }
  return error?.message || "Something went wrong.";
}

function showAlert(message, isError = false) {
  ui.alertHidden = false;
  ui.alertText = message;
  ui.alertIsError = isError;
  enforceUi();
}

function clearAlert() {
  ui.alertHidden = true;
  enforceUi();
}

function setFormBusy(form, busy, busyLabel) {
  const button = form.querySelector("button[type='submit']");
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.defaultLabel;
}

function statusLabel(status) {
  return String(status || "uploaded").replaceAll("_", " ");
}

// Which of the three upload panels is visible. Page-level events are
// delegated so dynamically rendered material and review rows stay usable.
const ui = {
  activeUploadTab: "syllabus",
  reviewHidden: true,
  alertHidden: true,
  alertText: "",
  alertIsError: false,
};

function enforceUi() {
  ["syllabus", "lecture", "reference"].forEach(tab => {
    const button = byId(`${tab}-upload-tab`);
    const panel = byId(`${tab}-upload-panel`);
    const active = tab === ui.activeUploadTab;
    if (button) { button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); }
    if (panel) panel.hidden = !active;
  });
  const review = byId("syllabus-review");
  if (review) review.hidden = ui.reviewHidden;
  const alert = byId("materials-alert");
  if (alert) {
    alert.hidden = ui.alertHidden;
    alert.textContent = ui.alertText;
    alert.classList.toggle("error", ui.alertIsError);
  }
}

function openReviewPanel() {
  ui.reviewHidden = false;
  enforceUi();
}

function closeReviewPanel() {
  ui.reviewHidden = true;
  enforceUi();
}

function closeOpenMenu() {
  if (!openMenuTrigger) return;
  const list = openMenuTrigger.parentElement?.querySelector(".material-actions-list");
  if (list) list.hidden = true;
  openMenuTrigger.setAttribute("aria-expanded", "false");
  openMenuTrigger = null;
}

function toggleMenu(trigger) {
  const list = trigger.parentElement?.querySelector(".material-actions-list");
  if (!list) return;
  const wasOpen = trigger === openMenuTrigger;
  closeOpenMenu();
  if (!wasOpen) {
    list.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    openMenuTrigger = trigger;
  }
}

function createMaterialRow(material) {
  const row = document.createElement("article");
  row.className = "material-row";
  row.dataset.materialId = material.material_id;

  const identity = document.createElement("div"); identity.className = "material-identity";
  const fileIcon = text("span", material.material_type === "slides" ? "P" : material.original_filename?.toLowerCase().endsWith(".pdf") ? "PDF" : "▤", `material-file-icon ${material.material_type}`);
  const identityCopy = document.createElement("div");
  identityCopy.append(text("div", material.original_filename, "material-name"));
  const details = [material.source_key, material.source_date].filter(Boolean).join(" · ");
  identityCopy.append(text("div", details || (material.legacy ? "Existing course source" : "Added by you"), "material-meta")); identity.append(fileIcon, identityCopy);
  row.append(identity);
  row.append(text("div", material.material_type, "material-type"));
  row.append(text("time", material.uploaded_at ? new Date(material.uploaded_at).toLocaleString([], { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "Existing", "material-uploaded"));

  const shownStatus = material.review_status === "superseded" ? "superseded" : material.processing_status;
  const status = text("span", statusLabel(shownStatus), `material-status material-status-${shownStatus}`);
  if (material.failure_message) status.title = material.failure_message;
  row.append(status);

  const actionsWrap = document.createElement("div");
  actionsWrap.className = "material-actions";
  if (!material.legacy) {
    const items = [];
    if (material.processing_status === "needs_review") items.push({ action: "review", label: "Review" });
    if (material.processing_status === "failed") items.push({ action: "retry", label: "Retry" });
    if (material.processing_status === "ready") items.push({ action: "download", label: "Download", href: `/api/courses/${encodeURIComponent(courseId)}/materials/${material.material_id}/download/` });
    items.push({ action: "delete", label: "Delete", danger: true });

    const menu = document.createElement("div");
    menu.className = "material-actions-menu";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "material-actions-trigger";
    trigger.dataset.action = "toggle-menu";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-label", `Actions for ${material.original_filename}`);
    trigger.innerHTML = '<svg class="ot-icon" aria-hidden="true"><use href="#ot-icon-more"/></svg>';
    menu.append(trigger);

    const list = document.createElement("div");
    list.className = "material-actions-list";
    list.hidden = true;
    items.forEach(item => {
      const el = document.createElement(item.href ? "a" : "button");
      if (item.href) el.href = item.href; else el.type = "button";
      el.textContent = item.label;
      el.dataset.action = item.action;
      el.dataset.materialId = material.material_id;
      if (item.danger) el.classList.add("danger");
      list.append(el);
    });
    menu.append(list);
    actionsWrap.append(menu);
  }
  row.append(actionsWrap);
  return row;
}

async function loadMaterials({ quiet = false } = {}) {
  const loading = byId("materials-loading");
  const error = byId("materials-error");
  const empty = byId("materials-empty");
  const list = byId("materials-list");
  if (!quiet) loading.hidden = false;
  error.hidden = true;
  empty.hidden = true;
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/`);
    const rows = data.materials || [];
    const head = document.createElement("div"); head.className = "materials-table-head"; ["Name", "Type", "Uploaded", "Status", "Actions"].forEach(label => head.append(text("span", label)));
    list.replaceChildren(head, ...rows.map(createMaterialRow));
    list.hidden = rows.length === 0;
    empty.hidden = rows.length !== 0;
    loading.hidden = true;
    window.clearTimeout(pollTimer);
    if (rows.some(material => ["uploaded", "processing"].includes(material.processing_status))) {
      pollTimer = window.setTimeout(() => loadMaterials({ quiet: true }), 2000);
    }
  } catch (errorValue) {
    loading.hidden = true;
    list.hidden = true;
    error.querySelector("p").textContent = errorMessage(errorValue);
    error.hidden = false;
  }
}

function makeCheckboxRow(fields) {
  const row = document.createElement("label");
  row.className = "review-row";
  const include = document.createElement("input");
  include.type = "checkbox";
  include.checked = true;
  include.className = "review-include";
  row.append(include, fields);
  return row;
}

function inputFor(value, type = "text") {
  const input = document.createElement("input");
  input.className = "input";
  input.type = type;
  input.value = value ?? "";
  return input;
}

function renderReviewList(containerId, values, builder) {
  const container = byId(containerId);
  const nodes = (values || []).map(builder);
  container.replaceChildren(...(nodes.length ? nodes : [text("p", "No items extracted.", "material-meta")]));
}

function openReview(material) {
  reviewMaterialId = material.material_id;
  reviewCandidate = structuredClone(material.candidate || {});
  byId("review-course-name").value = reviewCandidate.course_name || courseId;
  byId("review-source-name").textContent = `From ${material.original_filename}`;
  const discardButton = byId("cancel-syllabus-review");
  if (discardButton) discardButton.textContent = "Discard extraction";
  apiRequest(`/api/courses/${encodeURIComponent(courseId)}/syllabus/`)
    .then(() => { if (discardButton) discardButton.textContent = "Keep current version"; })
    .catch(() => { if (discardButton) discardButton.textContent = "Discard extraction"; });

  renderReviewList("review-dates", reviewCandidate.dates, item => {
    const fields = document.createElement("div");
    fields.className = "review-row-fields";
    fields.dataset.kind = "date";
    const date = inputFor(item.date, "date"); date.dataset.field = "date";
    const title = inputFor(item.title); title.dataset.field = "title";
    const type = document.createElement("select"); type.className = "input"; type.dataset.field = "type";
    [["test_quiz", "Test / quiz"], ["hw", "Homework"], ["project", "Project"], ["class", "Class / reading"], ["other", "Other"]].forEach(([value, label]) => {
      const option = text("option", label);
      option.value = value;
      option.selected = item.type === value;
      type.append(option);
    });
    fields.append(date, title, type);
    return makeCheckboxRow(fields);
  });

  renderReviewList("review-topics", reviewCandidate.topics, topic => {
    const fields = document.createElement("div"); fields.className = "review-row-fields"; fields.dataset.kind = "topic";
    const value = inputFor(topic); value.dataset.field = "topic"; fields.append(value);
    return makeCheckboxRow(fields);
  });

  renderReviewList("review-grading", reviewCandidate.grading, item => {
    const fields = document.createElement("div"); fields.className = "review-row-fields"; fields.dataset.kind = "grading";
    [["component", "text"], ["weight_pct", "number"], ["total_items", "number"], ["drop_lowest", "number"]].forEach(([key, type]) => {
      const input = inputFor(item[key], type); input.dataset.field = key; input.placeholder = key.replaceAll("_", " ");
      if (type === "number") input.step = "any";
      fields.append(input);
    });
    return makeCheckboxRow(fields);
  });

  openReviewPanel();
  byId("syllabus-review")?.scrollIntoView({ behavior: "smooth", block: "start" });
  byId("review-course-name").focus({ preventScroll: true });
}

async function fetchReview(materialId) {
  clearAlert();
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/${materialId}/`);
    openReview(data.material);
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

function includedReviewFields(kind) {
  return [...document.querySelectorAll(`#syllabus-review [data-kind='${kind}']`)]
    .filter(fields => fields.closest(".review-row").querySelector(".review-include").checked);
}

function collectCandidate() {
  const candidate = { ...reviewCandidate, course_id: courseId, course_name: byId("review-course-name").value.trim() };
  candidate.dates = includedReviewFields("date").map(fields => ({
    date: fields.querySelector("[data-field='date']").value,
    title: fields.querySelector("[data-field='title']").value.trim(),
    type: fields.querySelector("[data-field='type']").value,
  }));
  candidate.topics = includedReviewFields("topic").map(fields => fields.querySelector("[data-field='topic']").value.trim()).filter(Boolean);
  candidate.grading = includedReviewFields("grading").map(fields => {
    const item = {
      component: fields.querySelector("[data-field='component']").value.trim(),
      weight_pct: Number(fields.querySelector("[data-field='weight_pct']").value),
    };
    ["total_items", "drop_lowest"].forEach(key => {
      const value = fields.querySelector(`[data-field='${key}']`).value;
      if (value !== "") item[key] = Number(value);
    });
    return item;
  });
  return candidate;
}

function resetDropzone(form) {
  const zone = form.querySelector("[data-dropzone-for]");
  const filename = zone?.querySelector(".materials-dropzone-filename");
  if (filename) filename.textContent = "";
}

async function submitUpload(form, endpoint, busyLabel, successLabel, onSuccess) {
  clearAlert();
  setFormBusy(form, true, busyLabel);
  try {
    const data = await apiRequest(endpoint, { method: "POST", body: new FormData(form) });
    form.reset();
    resetDropzone(form);
    showAlert(successLabel);
    if (onSuccess) onSuccess(data);
    await loadMaterials({ quiet: true });
  } catch (error) {
    showAlert(errorMessage(error), true);
    if (error.data?.material?.processing_status) await loadMaterials({ quiet: true });
  } finally {
    setFormBusy(form, false, busyLabel);
  }
}

async function deleteMaterial(materialId, filename) {
  const confirmation = await promptDialog({ kicker: "Permanent action", title: `Delete “${filename}”?`, message: "This material and its processed content will be permanently removed.", inputLabel: "Type DELETE to confirm", requiredValue: "DELETE", confirmLabel: "Delete material", danger: true });
  if (confirmation === null) return;
  try {
    await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/${materialId}/`, {
      method: "DELETE",
      body: JSON.stringify({ confirmation }),
    });
    if (reviewMaterialId === materialId) closeReviewPanel();
    showAlert("Material deleted.");
    await loadMaterials({ quiet: true });
  } catch (error) {
    showAlert(errorMessage(error), true);
  }
}

async function discardReview() {
  if (!reviewMaterialId || !(await confirmDialog({ title: "Discard this extraction?", message: "Your currently confirmed course data will remain unchanged.", confirmLabel: "Discard extraction", danger: true }))) return;
  try {
    await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/${reviewMaterialId}/`, { method: "DELETE", body: JSON.stringify({ confirmation: "DELETE" }) });
    closeReviewPanel(); reviewMaterialId = null; reviewCandidate = null;
    showAlert("Extraction discarded. Your current course version was kept."); await loadMaterials({ quiet: true });
  } catch (error) { showAlert(errorMessage(error), true); }
}

async function retryMaterial(materialId) {
  clearAlert();
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/${materialId}/retry/`, { method: "POST" });
    showAlert("Retrying — check back in a moment.");
    if (data.material?.processing_status === "needs_review") openReview(data.material);
    await loadMaterials({ quiet: true });
  } catch (error) {
    showAlert(errorMessage(error), true);
    await loadMaterials({ quiet: true });
  }
}

const UPLOAD_ENDPOINTS = {
  "syllabus-upload-form": { path: "syllabus/extract/", busy: "Extracting…", success: "Extraction is ready for your review.", onSuccess: data => openReview(data.material) },
  "lecture-upload-form": { path: "notes/chunk/", busy: "Processing…", success: "Lecture material is ready." },
  "reference-upload-form": { path: "references/", busy: "Processing…", success: "Reference is ready." },
};

function dragDepthMap() {
  if (!window.__materialsDragDepth) window.__materialsDragDepth = new WeakMap();
  return window.__materialsDragDepth;
}

function bindDelegatedEvents() {
  document.addEventListener("click", event => {
    const tab = event.target.closest("[data-upload-tab]");
    if (tab) {
      ui.activeUploadTab = tab.dataset.uploadTab;
      enforceUi();
      return;
    }

    if (event.target.closest("#refresh-materials")) { loadMaterials(); return; }
    if (event.target.closest("#materials-error button")) { loadMaterials(); return; }
    if (event.target.closest("#cancel-syllabus-review")) { discardReview(); return; }
    if (event.target.closest("#add-review-date")) {
      const fields = document.createElement("div"); fields.className = "review-row-fields"; fields.dataset.kind = "date";
      const date = inputFor("", "date"); date.dataset.field = "date"; const title = inputFor(""); title.dataset.field = "title";
      const type = document.createElement("select"); type.className = "input"; type.dataset.field = "type";
      [["hw", "Homework"], ["test_quiz", "Test / quiz"], ["project", "Project"], ["class", "Class / reading"], ["other", "Other"]].forEach(([value, label]) => { const option = text("option", label); option.value = value; type.append(option); });
      fields.append(date, title, type); byId("review-dates").append(makeCheckboxRow(fields)); date.focus(); return;
    }

    const menuTrigger = event.target.closest("[data-action='toggle-menu']");
    if (menuTrigger) { toggleMenu(menuTrigger); return; }

    const actionEl = event.target.closest("[data-action]");
    if (actionEl && actionEl.dataset.materialId) {
      const { action, materialId } = actionEl.dataset;
      closeOpenMenu();
      const row = actionEl.closest(".material-row");
      const filename = row?.querySelector(".material-name")?.textContent || "this material";
      if (action === "review") fetchReview(materialId);
      else if (action === "retry") retryMaterial(materialId);
      else if (action === "delete") deleteMaterial(materialId, filename);
      // "download" is a plain <a href> and needs no JS handling.
      return;
    }

    if (openMenuTrigger && !event.target.closest(".material-actions-menu")) closeOpenMenu();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && openMenuTrigger) {
      const trigger = openMenuTrigger;
      closeOpenMenu();
      trigger.focus();
    }
  });

  document.addEventListener("change", event => {
    if (!event.target.matches("input[type='file']")) return;
    const zone = event.target.closest(".materials-dropzone");
    const filenameEl = zone?.querySelector(".materials-dropzone-filename");
    if (filenameEl) filenameEl.textContent = event.target.files?.[0]?.name || "";
  });

  document.addEventListener("dragover", event => {
    const zone = event.target.closest("[data-dropzone-for]");
    if (!zone) return;
    event.preventDefault();
  });

  document.addEventListener("dragenter", event => {
    const zone = event.target.closest("[data-dropzone-for]");
    if (!zone) return;
    event.preventDefault();
    const depth = dragDepthMap();
    depth.set(zone, (depth.get(zone) || 0) + 1);
    zone.classList.add("materials-dropzone-active");
  });

  document.addEventListener("dragleave", event => {
    const zone = event.target.closest("[data-dropzone-for]");
    if (!zone) return;
    const depth = dragDepthMap();
    const next = Math.max(0, (depth.get(zone) || 0) - 1);
    depth.set(zone, next);
    if (next === 0) zone.classList.remove("materials-dropzone-active");
  });

  document.addEventListener("drop", event => {
    const zone = event.target.closest("[data-dropzone-for]");
    if (!zone) return;
    event.preventDefault();
    dragDepthMap().set(zone, 0);
    zone.classList.remove("materials-dropzone-active");
    const form = byId(zone.dataset.dropzoneFor);
    const input = form?.querySelector("input[type='file']");
    const droppedFiles = event.dataTransfer?.files;
    if (input && droppedFiles && droppedFiles.length) {
      input.files = droppedFiles;
      const filenameEl = zone.querySelector(".materials-dropzone-filename");
      if (filenameEl) filenameEl.textContent = droppedFiles[0].name;
    }
  });

  document.addEventListener("submit", event => {
    const form = event.target;
    const config = UPLOAD_ENDPOINTS[form.id];
    if (config) {
      event.preventDefault();
      submitUpload(form, `/api/courses/${encodeURIComponent(courseId)}/${config.path}`, config.busy, config.success, config.onSuccess);
      return;
    }
    if (form.id === "syllabus-review-form") {
      event.preventDefault();
      setFormBusy(form, true, "Confirming…");
      apiRequest(`/api/courses/${encodeURIComponent(courseId)}/materials/${reviewMaterialId}/confirm/`, {
        method: "POST",
        body: JSON.stringify({ confirm: true, syllabus: collectCandidate() }),
      }).then(async () => {
        closeReviewPanel();
        reviewMaterialId = null;
        reviewCandidate = null;
        showAlert("Syllabus confirmed. Grounded course tools now use this reviewed version.");
        await loadMaterials({ quiet: true });
        courseHeader?.refresh();
      }).catch(error => {
        showAlert(errorMessage(error), true);
      }).finally(() => {
        setFormBusy(form, false, "Confirming…");
      });
    }
  });
}

if (root && courseId) {
  enforceUi();
  bindDelegatedEvents();
  courseHeader = initCourseHeader(courseId);
  loadMaterials();
}
