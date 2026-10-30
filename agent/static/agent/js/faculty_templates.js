const library = document.querySelector("#template-library");
const detail = document.querySelector("#template-detail");
const search = document.querySelector("#template-search");
const emptyState = document.querySelector("#template-empty");
const builder = document.querySelector("#template-builder");
const form = document.querySelector("#template-form");
const storageKey = "ontrack.facultyTemplates";
const forbiddenStudentFields = ["studentName", "studentId", "studentGPA", "completedCourses", "studentAcademicHistory"];

const termLabels = [
  "Year 1 — Fall", "Year 1 — Spring", "Year 2 — Fall", "Year 2 — Spring",
  "Year 3 — Fall", "Year 3 — Spring", "Year 4 — Fall", "Year 4 — Spring",
];

const systemTemplates = [
  {
    id: "four-year-plan", name: "4-Year Plan Template", category: "4-year-plan",
    description: "Traditional degree path with semester-by-semester course planning.",
    tags: ["4-Year Plan", "Undergraduate", "Core"], updated: "Aug 28, 2026", featured: true,
    icon: "study", tone: "purple", owner: "OnTrack Team",
    summary: "This template includes 8 semesters with core courses, major requirements, and electives.",
    terms: ["Orientation, core requirements, introductory courses", "Core requirements, major prerequisites", "Major requirements, electives", "Major requirements, general education", "Advanced major courses, electives", "Advanced major courses, electives", "Capstone, remaining requirements", "Capstone, graduation checklist"],
  },
  {
    id: "transfer-student", name: "Transfer Student Template", category: "transfer",
    description: "Degree plan for transfer students with flexible course mapping.",
    tags: ["Transfer", "Course Mapping", "Flexible"], updated: "Aug 20, 2026",
    icon: "trend", tone: "green", owner: "OnTrack Team",
    summary: "A flexible four-term structure for mapping accepted credits and remaining degree requirements.",
    terms: ["Transfer credit review, degree foundations", "Major prerequisites, general education", "Major requirements, electives", "Capstone, graduation review"],
  },
  {
    id: "major-exploration", name: "Major Exploration Template", category: "major-exploration",
    description: "Help students explore majors with sample course pathways.",
    tags: ["Exploration", "Multiple Majors", "Guidance"], updated: "Aug 15, 2026",
    icon: "cora", tone: "blue", owner: "OnTrack Team",
    summary: "A four-term exploration scaffold with shared foundations and major comparison checkpoints.",
    terms: ["Interest inventory, shared foundations", "Introductory pathways, reflection", "Pathway comparison, support courses", "Major decision, next-step requirements"],
  },
  {
    id: "graduation-check", name: "Graduation Check Template", category: "graduation-check",
    description: "Track remaining degree requirements and outstanding courses.",
    tags: ["Graduation", "Requirements", "Audit"], updated: "Aug 12, 2026",
    icon: "check", tone: "green", owner: "OnTrack Team",
    summary: "A two-term audit scaffold for outstanding requirements, minimum credits, and graduation milestones.",
    terms: ["Remaining requirements, residency review", "Capstone, final audit, graduation checklist"],
  },
  {
    id: "advising-notes", name: "Semester Advising Notes", category: "advising-notes",
    description: "Structured notes for advising sessions with action items and follow-ups.",
    tags: ["Advising Notes", "Checklists", "Follow-up"], updated: "Aug 10, 2026",
    icon: "assignment", tone: "purple", owner: "OnTrack Team",
    summary: "A reusable advising agenda organized around goals, decisions, actions, and follow-up.",
    terms: ["Goals and discussion topics", "Decisions and action items", "Referrals and follow-up"],
  },
];

let activeFilter = "all";
let selectedId = "four-year-plan";
let editingId = null;
let lastFocused = null;
let facultyTemplates = loadFacultyTemplates();

function loadFacultyTemplates() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(stored) ? stored.filter(templateIsSafe) : [];
  } catch (_error) {
    return [];
  }
}

function templateIsSafe(template) {
  return template && !forbiddenStudentFields.some(field => Object.hasOwn(template, field));
}

function saveFacultyTemplates() {
  localStorage.setItem(storageKey, JSON.stringify(facultyTemplates.map(sanitizeTemplate)));
}

function sanitizeTemplate(template) {
  const safe = { ...template };
  forbiddenStudentFields.forEach(field => delete safe[field]);
  return safe;
}

function allTemplates() {
  return [...systemTemplates, ...facultyTemplates];
}

function getTemplate(id) {
  return allTemplates().find(template => template.id === id) || systemTemplates[0];
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("ot-icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#ot-icon-${name}`);
  svg.append(use);
  return svg;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderLibrary() {
  const query = search.value.trim().toLowerCase();
  const templates = allTemplates().filter(template => {
    const matchesFilter = activeFilter === "all" || template.category === activeFilter;
    const haystack = [template.name, template.description, ...(template.tags || [])].join(" ").toLowerCase();
    return matchesFilter && haystack.includes(query);
  });

  library.replaceChildren(...templates.map(renderCard));
  library.hidden = templates.length === 0;
  emptyState.hidden = templates.length !== 0;
  if (templates.length && !templates.some(template => template.id === selectedId)) selectTemplate(templates[0].id, false);
}

function renderCard(template) {
  const card = element("article", `faculty-template-card${template.id === selectedId ? " is-selected" : ""}`);
  card.dataset.templateCard = template.id;
  if (template.id === "advising-notes") card.classList.add("faculty-template-card-wide");

  const iconBlock = element("div", `faculty-template-icon faculty-template-icon-${template.tone || "purple"}`);
  iconBlock.append(icon(template.icon || "material"));
  const copy = element("div", "faculty-template-card-copy");
  copy.append(element("h2", "", template.name), element("p", "", template.description));
  const tags = element("div", "faculty-template-tags");
  (template.tags || []).forEach(tag => tags.append(element("span", "", tag)));
  copy.append(tags, element("small", "", `Updated ${template.updated}`));

  const actions = element("div", "faculty-template-card-actions");
  const use = element("button", "", "Use template");
  use.type = "button"; use.dataset.useTemplate = template.id; use.prepend(icon("material"));
  const preview = element("button", "", "Preview");
  preview.type = "button"; preview.dataset.previewTemplate = template.id; preview.prepend(icon("search"));
  const more = element("button", "faculty-template-more", "");
  more.type = "button"; more.dataset.templateMenu = template.id; more.setAttribute("aria-label", `More actions for ${template.name}`); more.setAttribute("aria-expanded", "false"); more.append(icon("more"));
  actions.append(use, preview, more);
  card.append(iconBlock, copy, actions);
  card.addEventListener("click", event => {
    if (!event.target.closest("button")) selectTemplate(template.id);
  });
  return card;
}

function selectTemplate(id, shouldFocus = false) {
  selectedId = getTemplate(id).id;
  document.querySelectorAll("[data-template-card]").forEach(card => card.classList.toggle("is-selected", card.dataset.templateCard === selectedId));
  renderDetail();
  if (shouldFocus && matchMedia("(max-width: 1100px)").matches) detail.focus({ preventScroll: true });
}

function setText(selector, value) {
  const node = detail.querySelector(selector);
  if (node) node.textContent = value;
}

function renderDetail() {
  const template = getTemplate(selectedId);
  setText("[data-detail-name]", template.name);
  setText("[data-detail-description]", template.description);
  setText("[data-detail-updated]", `Updated ${template.updated}`);
  setText("[data-detail-owner]", `Created by ${template.owner}`);
  setText("[data-structure-summary]", template.summary);
  const featured = detail.querySelector("[data-detail-featured]");
  featured.hidden = !template.featured;
  const tags = detail.querySelector("[data-detail-tags]");
  tags.replaceChildren(...(template.tags || []).map(tag => element("span", "", tag)));
  const iconBlock = detail.querySelector(".faculty-template-icon");
  iconBlock.className = `faculty-template-icon faculty-template-icon-${template.tone || "purple"}`;
  iconBlock.replaceChildren(icon(template.icon || "material"));
  renderTerms(template);
}

function renderTerms(template) {
  const container = detail.querySelector("[data-template-terms]");
  const min = template.creditMin ?? 12;
  const max = template.creditMax ?? 16;
  container.replaceChildren(...template.terms.map((copy, index) => {
    const item = element("details", "faculty-template-term");
    const summary = element("summary", "");
    summary.append(element("span", "", termLabels[index] || `Section ${index + 1}`), element("small", "", copy), element("b", "", `${min}–${max} credits`));
    item.append(summary, element("p", "", `Placeholder categories: ${copy}. Replace these categories with grounded requirements during the active Cora session.`));
    return item;
  }));
}

function useTemplate(id) {
  const template = getTemplate(id);
  sessionStorage.setItem("ontrack.selectedFacultyTemplate", JSON.stringify({
    id: template.id, name: template.name, category: template.category, tags: template.tags,
    terms: template.terms, creditMin: template.creditMin ?? 12, creditMax: template.creditMax ?? 16,
  }));
  window.location.assign("/faculty/");
}

function previewTemplate(id) {
  selectTemplate(id, true);
  detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

function openBuilder(template = null) {
  lastFocused = document.activeElement;
  editingId = template?.isSystem ? null : template?.id || null;
  form.reset();
  form.elements.termCount.value = 8;
  form.elements.creditMin.value = 12;
  form.elements.creditMax.value = 16;
  form.elements.sections.value = "Major Requirements, General Education, Electives, Support Courses, Capstone";
  if (template && !template.isSystem) {
    form.elements.name.value = template.name;
    form.elements.category.value = template.category;
    form.elements.description.value = template.description;
    form.elements.tags.value = template.tags.join(", ");
    form.elements.termCount.value = template.terms.length;
    form.elements.creditMin.value = template.creditMin;
    form.elements.creditMax.value = template.creditMax;
    form.elements.sections.value = template.sections.join(", ");
    form.elements.placeholders.value = (template.placeholders || []).join(", ");
  }
  builder.hidden = false;
  document.body.classList.add("faculty-template-modal-open");
  form.elements.name.focus();
}

function closeBuilder() {
  builder.hidden = true;
  document.body.classList.remove("faculty-template-modal-open");
  lastFocused?.focus();
}

function commaList(value) {
  return value.split(",").map(item => item.trim()).filter(Boolean);
}

function buildFacultyTemplate(data) {
  const termCount = Number(data.get("termCount"));
  const sections = commaList(data.get("sections"));
  return sanitizeTemplate({
    id: editingId || `faculty-${crypto.randomUUID()}`, isSystem: false,
    name: data.get("name").trim(), category: data.get("category"),
    description: data.get("description").trim(), tags: commaList(data.get("tags")),
    updated: new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date()),
    icon: "material", tone: "purple", owner: window.CURRENT_USER_NAME || "Faculty",
    summary: `A faculty-created template with ${termCount} reusable planning sections.`,
    creditMin: Number(data.get("creditMin")), creditMax: Number(data.get("creditMax")),
    sections, placeholders: commaList(data.get("placeholders")),
    terms: Array.from({ length: termCount }, (_, index) => sections[index % sections.length] || "Planning categories and placeholders"),
  });
}

function showMenu(button, template) {
  document.querySelector(".faculty-template-menu")?.remove();
  const menu = element("div", "faculty-template-menu");
  const actions = template.isSystem
    ? [["Duplicate template", "duplicate"], ["Preview", "preview"], ["Use template", "use"]]
    : [["Edit template", "edit"], ["Duplicate template", "duplicate"], ["Rename", "rename"], ["Delete", "delete"]];
  actions.forEach(([label, action]) => {
    const item = element("button", action === "delete" ? "is-danger" : "", label);
    item.type = "button";
    item.addEventListener("click", () => handleMenuAction(action, template));
    menu.append(item);
  });
  button.closest(".faculty-template-card").append(menu);
  button.setAttribute("aria-expanded", "true");
}

function handleMenuAction(action, template) {
  document.querySelector(".faculty-template-menu")?.remove();
  if (action === "use") return useTemplate(template.id);
  if (action === "preview") return previewTemplate(template.id);
  if (action === "edit") return openBuilder(template);
  if (action === "duplicate") {
    const copy = sanitizeTemplate({ ...template, id: `faculty-${crypto.randomUUID()}`, name: `${template.name} Copy`, owner: window.CURRENT_USER_NAME || "Faculty", isSystem: false, featured: false });
    facultyTemplates.unshift(copy); saveFacultyTemplates(); selectedId = copy.id; renderLibrary(); renderDetail(); return;
  }
  if (action === "rename") {
    const name = window.prompt("Rename template", template.name)?.trim();
    if (!name) return;
    template.name = name; template.updated = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date());
    saveFacultyTemplates(); renderLibrary(); renderDetail(); return;
  }
  if (action === "delete" && window.confirm(`Delete “${template.name}”?`)) {
    facultyTemplates = facultyTemplates.filter(item => item.id !== template.id);
    selectedId = systemTemplates[0].id; saveFacultyTemplates(); renderLibrary(); renderDetail();
  }
}

library.addEventListener("click", event => {
  const use = event.target.closest("[data-use-template]");
  if (use) return useTemplate(use.dataset.useTemplate);
  const preview = event.target.closest("[data-preview-template]");
  if (preview) return previewTemplate(preview.dataset.previewTemplate);
  const menu = event.target.closest("[data-template-menu]");
  if (menu) showMenu(menu, getTemplate(menu.dataset.templateMenu));
});

search.addEventListener("input", renderLibrary);
document.querySelectorAll("[data-template-filter]").forEach(button => button.addEventListener("click", () => {
  activeFilter = button.dataset.templateFilter;
  document.querySelectorAll("[data-template-filter]").forEach(item => {
    const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-pressed", String(active));
  });
  renderLibrary();
}));

document.querySelector("[data-clear-template-filters]")?.addEventListener("click", () => {
  search.value = ""; activeFilter = "all"; document.querySelector('[data-template-filter="all"]').click(); search.focus();
});
document.querySelectorAll("[data-open-template-builder]").forEach(button => button.addEventListener("click", () => openBuilder()));
document.querySelectorAll("[data-close-template-builder]").forEach(button => button.addEventListener("click", closeBuilder));
document.querySelector("[data-use-selected]")?.addEventListener("click", () => useTemplate(selectedId));
document.querySelector("[data-preview-selected]")?.addEventListener("click", () => detail.querySelector(".faculty-template-term")?.setAttribute("open", ""));

document.querySelectorAll("[data-detail-tab]").forEach(button => button.addEventListener("click", () => {
  const structure = button.dataset.detailTab === "structure";
  document.querySelector("#template-structure-panel").hidden = !structure;
  document.querySelector("#template-about-panel").hidden = structure;
  document.querySelectorAll("[data-detail-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab === button)));
}));

form.addEventListener("submit", event => {
  event.preventDefault();
  const template = buildFacultyTemplate(new FormData(form));
  facultyTemplates = editingId ? facultyTemplates.map(item => item.id === editingId ? template : item) : [template, ...facultyTemplates];
  selectedId = template.id; saveFacultyTemplates(); closeBuilder(); renderLibrary(); renderDetail();
});

builder.addEventListener("click", event => { if (event.target === builder) closeBuilder(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !builder.hidden) closeBuilder(); });
document.addEventListener("click", event => { if (!event.target.closest("[data-template-menu], .faculty-template-menu")) document.querySelector(".faculty-template-menu")?.remove(); });

systemTemplates.forEach(template => { template.isSystem = true; });
renderLibrary();
renderDetail();

// Plan skeletons / Export formats tabs
const ftTabs = [...document.querySelectorAll("[data-ft-tab]")];
const ftPanels = [...document.querySelectorAll("[data-ft-panel]")];
function showFacultyTab(name) {
  ftTabs.forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.ftTab === name)));
  ftPanels.forEach(panel => { panel.hidden = panel.dataset.ftPanel !== name; });
}
ftTabs.forEach(tab => tab.addEventListener("click", () => showFacultyTab(tab.dataset.ftTab)));

// Export format preference (a layout id only; never student data)
const EXPORT_FORMAT_KEY = "ontrack.facultyExportFormat";
const EXPORT_LAYOUTS = ["term_table", "year_grid", "plan_notes"];
function readExportFormat() {
  try {
    const stored = localStorage.getItem(EXPORT_FORMAT_KEY);
    return EXPORT_LAYOUTS.includes(stored) ? stored : "term_table";
  } catch { return "term_table"; }
}
function renderExportFormatDefault() {
  const current = readExportFormat();
  document.querySelectorAll("[data-format]").forEach(card => {
    const isDefault = card.dataset.format === current;
    card.querySelector("[data-default-chip]").hidden = !isDefault;
    card.querySelector("[data-set-default-format]").hidden = isDefault;
  });
}
document.querySelectorAll("[data-set-default-format]").forEach(button => button.addEventListener("click", () => {
  const layout = button.dataset.setDefaultFormat;
  if (!EXPORT_LAYOUTS.includes(layout)) return;
  try { localStorage.setItem(EXPORT_FORMAT_KEY, layout); } catch { /* storage unavailable: preference not saved */ }
  renderExportFormatDefault();
}));
renderExportFormatDefault();
