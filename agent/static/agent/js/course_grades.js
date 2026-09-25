import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";
import { initCourseHeader } from "./core/course_header.js";
import { focusFirst, restoreFocus } from "./core/modal.js";
import { confirmDialog } from "./core/dialogs.js?v=20260901-1";
import { showToast } from "./core/toast.js";

initNavigation();
const root = document.querySelector("[data-page-section='course-grades']");
const courseId = root?.dataset.courseId;
const byId = id => document.getElementById(id);

let grade = null; // {overall_pct, letter, grade_scale, categories}
let items = [];
let filterCategory = "all";
let sortMode = "newest";
let lastFocused = null;

const trim = n => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, ""));
const scoreBadgeClass = pct => (pct >= 90 ? "high" : pct >= 75 ? "mid" : "low");
function formatDate(value) {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(y, m - 1, d));
}

function renderSummary() {
  const overall = grade.overall_pct;
  byId("grades-current-pct").textContent = overall == null ? "—" : `${overall}% · ${grade.letter}`;
  byId("grades-current-detail").textContent = items.length ? `Based on ${items.length} graded item${items.length === 1 ? "" : "s"}` : "No grades entered yet.";

  const sumScore = items.reduce((sum, i) => sum + i.score, 0);
  const sumMax = items.reduce((sum, i) => sum + i.max_points, 0);
  byId("grades-points").textContent = items.length ? `${trim(sumScore)} / ${trim(sumMax)}` : "— / —";

  byId("grades-graded-count").textContent = String(items.length);
  const allTotalsKnown = grade.categories.every(c => c.total_items != null);
  const totalItems = grade.categories.reduce((sum, c) => sum + (c.total_items || 0), 0);
  byId("grades-graded-detail").textContent = allTotalsKnown && totalItems > 0 ? `${items.length} of ${totalItems}` : `${items.length} graded`;

  renderGoal();
}

function cutoffsAscending() {
  return [...(grade.grade_scale?.cutoffs || [])].sort((a, b) => a.min_pct - b.min_pct);
}

function renderGoal(chosenTarget) {
  const select = byId("grades-goal-target");
  const cutoffs = cutoffsAscending();
  if (!cutoffs.length || grade.overall_pct == null) {
    select.disabled = true;
    select.replaceChildren();
    byId("grades-goal-letter").textContent = "—";
    byId("grades-goal-detail").textContent = "Add grades to set a goal.";
    return;
  }

  select.disabled = false;
  select.replaceChildren(...cutoffs.map(c => Object.assign(document.createElement("option"), { value: String(c.min_pct), textContent: c.letter })));

  let target = chosenTarget;
  if (!target) {
    const next = cutoffs.find(c => c.min_pct > grade.overall_pct);
    target = String((next || cutoffs[cutoffs.length - 1]).min_pct);
  }
  select.value = target;
  const cutoff = cutoffs.find(c => String(c.min_pct) === target) || cutoffs[cutoffs.length - 1];
  byId("grades-goal-letter").textContent = cutoff.letter;
  loadGoalProgress(cutoff.min_pct);
}

async function loadGoalProgress(targetPct) {
  const detail = byId("grades-goal-detail");
  detail.textContent = "Calculating…";
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/whatif/?target=${encodeURIComponent(targetPct)}`);
    const needed = data.grade_needed;
    if (needed.locked) {
      detail.textContent = needed.achievable ? `Already locked in at ${needed.ceiling_pct}%.` : `Not reachable — capped at ${needed.ceiling_pct}%.`;
    } else if (!needed.achievable) {
      detail.textContent = `Not reachable even at 100% on everything remaining (ceiling ${needed.ceiling_pct}%).`;
    } else {
      detail.textContent = `Need ${needed.p_needed}% on remaining work.`;
    }
  } catch (error) {
    detail.textContent = "Couldn't calculate — try again.";
  }
}

function renderBreakdown() {
  const host = byId("grades-breakdown-list");
  host.replaceChildren(...grade.categories.map(cat => {
    const row = document.createElement("div"); row.className = "grades-breakdown-row";
    const name = document.createElement("span"); name.textContent = cat.component;
    const weight = document.createElement("span"); weight.textContent = `${cat.weight_pct}%`;
    const avgWrap = document.createElement("div"); avgWrap.className = "grades-breakdown-avg";
    if (cat.avg_pct == null) {
      avgWrap.classList.add("grades-breakdown-empty");
      avgWrap.textContent = "No grades yet";
    } else {
      const bar = document.createElement("span"); bar.className = "course-progress";
      bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", `${cat.component} average`);
      bar.setAttribute("aria-valuemin", "0"); bar.setAttribute("aria-valuemax", "100"); bar.setAttribute("aria-valuenow", String(Math.round(cat.avg_pct)));
      const fill = document.createElement("span"); fill.style.width = `${Math.min(cat.avg_pct, 100)}%`;
      bar.append(fill);
      const pct = document.createElement("span"); pct.textContent = `${cat.avg_pct}%`;
      avgWrap.append(bar, pct);
    }
    const contribution = document.createElement("strong");
    contribution.textContent = cat.avg_pct == null ? "—" : `${Math.round(cat.weight_pct * cat.avg_pct) / 100}%`;
    row.append(name, weight, avgWrap, contribution);
    return row;
  }));
  byId("grades-breakdown-total-pct").textContent = grade.overall_pct == null ? "—" : `${grade.overall_pct}%`;
}

function populateWhatIfSelect() {
  const select = byId("grades-whatif-item");
  const previous = select.value;
  const options = [
    ...items.map(item => Object.assign(document.createElement("option"), { value: `item:${item.id}`, textContent: `${item.title} (${item.component})` })),
    ...grade.categories.map(cat => Object.assign(document.createElement("option"), { value: `new:${cat.component}`, textContent: `New item — ${cat.component}` })),
  ];
  select.replaceChildren(...options);
  if ([...select.options].some(o => o.value === previous)) select.value = previous;
}

async function runWhatIf(event) {
  event.preventDefault();
  const raw = byId("grades-whatif-item").value;
  const sep = raw.indexOf(":");
  const mode = raw.slice(0, sep);
  const key = raw.slice(sep + 1);
  const pct = parseFloat(byId("grades-whatif-pct").value);
  const errorEl = byId("grades-whatif-error");
  const resultEl = byId("grades-whatif-result");
  errorEl.hidden = true;
  if (!raw || !Number.isFinite(pct)) { errorEl.hidden = false; errorEl.textContent = "Pick an assignment and enter a score."; return; }

  const params = new URLSearchParams({ score: String(pct), max_points: "100" });
  if (mode === "item") params.set("item_id", key);
  else { params.set("component", key); params.set("title", "Hypothetical item"); }

  resultEl.textContent = "…";
  try {
    const projection = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/project/?${params}`);
    resultEl.textContent = projection.projected_pct == null ? "—" : `${projection.projected_pct}%`;
  } catch (error) {
    resultEl.textContent = "—";
    errorEl.hidden = false; errorEl.textContent = error.data?.detail || error.message;
  }
}

function renderGradebook() {
  const filterSelect = byId("grades-filter-category");
  filterSelect.replaceChildren(
    Object.assign(document.createElement("option"), { value: "all", textContent: "All categories" }),
    ...grade.categories.map(cat => Object.assign(document.createElement("option"), { value: cat.component, textContent: cat.component })),
  );
  filterSelect.value = filterCategory;

  let display = items.filter(i => filterCategory === "all" || i.component === filterCategory);
  display = display.slice().sort((a, b) => {
    if (sortMode === "newest") return (b.date || "").localeCompare(a.date || "");
    if (sortMode === "oldest") return (a.date || "").localeCompare(b.date || "");
    const pctA = a.score / a.max_points, pctB = b.score / b.max_points;
    return sortMode === "highest" ? pctB - pctA : pctA - pctB;
  });

  const weightByComponent = new Map(grade.categories.map(c => [c.component, c.weight_pct]));
  const host = byId("grades-item-list");
  host.replaceChildren(...display.map(item => {
    const row = document.createElement("div"); row.className = "grades-item-row";

    const titleCell = document.createElement("div"); titleCell.className = "grades-item-title";
    const icon = document.createElement("span"); icon.className = "grades-item-icon"; icon.setAttribute("aria-hidden", "true"); icon.textContent = "A";
    const titleText = document.createElement("span"); titleText.className = "grades-item-title-text"; titleText.textContent = item.title;
    titleCell.append(icon, titleText);

    const category = document.createElement("span"); category.textContent = item.component;

    const due = document.createElement("time");
    const formatted = formatDate(item.date);
    due.textContent = formatted || "—";
    if (item.date) due.dateTime = item.date;

    const pct = item.max_points ? Math.round((item.score / item.max_points) * 1000) / 10 : null;
    const scoreCell = document.createElement("span");
    const badge = document.createElement("span");
    badge.className = `grades-score-badge ${pct == null ? "low" : scoreBadgeClass(pct)}`;
    badge.textContent = `${trim(item.score)}/${trim(item.max_points)}`;
    scoreCell.append(badge);

    const weight = document.createElement("span");
    const w = weightByComponent.get(item.component);
    weight.textContent = w != null ? `${w}%` : "—";

    const menuWrap = document.createElement("div"); menuWrap.className = "grades-item-menu-wrap";
    const trigger = document.createElement("button");
    trigger.type = "button"; trigger.className = "grades-item-menu-trigger";
    trigger.setAttribute("aria-label", `Actions for ${item.title}`); trigger.setAttribute("aria-expanded", "false");
    trigger.dataset.gradeMenuTrigger = item.id;
    trigger.innerHTML = '<svg class="ot-icon" aria-hidden="true"><use href="#ot-icon-more"/></svg>';
    const menu = document.createElement("div"); menu.className = "grades-item-menu"; menu.hidden = true;
    menu.setAttribute("role", "menu"); menu.dataset.gradeMenu = item.id;
    const editBtn = document.createElement("button"); editBtn.type = "button"; editBtn.textContent = "Edit"; editBtn.dataset.gradeEdit = item.id;
    const deleteBtn = document.createElement("button"); deleteBtn.type = "button"; deleteBtn.className = "danger"; deleteBtn.textContent = "Delete"; deleteBtn.dataset.gradeDelete = item.id;
    menu.append(editBtn, deleteBtn);
    menuWrap.append(trigger, menu);

    row.append(titleCell, category, due, scoreCell, weight, menuWrap);
    return row;
  }));
  byId("grades-empty").hidden = items.length !== 0;
}

function populateComponentSelect(select) {
  select.replaceChildren(...grade.categories.map(cat => Object.assign(document.createElement("option"), { value: cat.component, textContent: cat.component })));
}

function setModal(open) {
  const backdrop = byId("grades-form-backdrop");
  backdrop.hidden = !open;
  backdrop.setAttribute("aria-hidden", String(!open));
  if (open) { lastFocused = document.activeElement; focusFirst(backdrop); }
  else restoreFocus(lastFocused);
}

function openAddModal() {
  byId("grades-form-title").textContent = "Add grade";
  byId("grades-item-id").value = "";
  byId("grades-item-form").reset();
  populateComponentSelect(byId("grades-item-component"));
  byId("grades-item-delete").hidden = true;
  byId("grades-form-error").hidden = true;
  setModal(true);
}

function openEditModal(itemId) {
  const item = items.find(i => i.id === itemId);
  if (!item) return;
  byId("grades-form-title").textContent = "Edit grade";
  byId("grades-item-id").value = item.id;
  populateComponentSelect(byId("grades-item-component"));
  byId("grades-item-component").value = item.component;
  byId("grades-item-title").value = item.title;
  byId("grades-item-score").value = item.score;
  byId("grades-item-max").value = item.max_points;
  byId("grades-item-date").value = item.date || "";
  byId("grades-item-delete").hidden = false;
  byId("grades-form-error").hidden = true;
  setModal(true);
}

async function saveItem(event) {
  event.preventDefault();
  const id = byId("grades-item-id").value;
  const payload = {
    component: byId("grades-item-component").value,
    title: byId("grades-item-title").value,
    score: parseFloat(byId("grades-item-score").value),
    max_points: parseFloat(byId("grades-item-max").value),
    date: byId("grades-item-date").value || null,
  };
  const errorEl = byId("grades-form-error"); errorEl.hidden = true;
  const saveBtn = byId("grades-item-save"); saveBtn.disabled = true;
  try {
    if (id) await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/items/${encodeURIComponent(id)}/`, { method: "PATCH", body: JSON.stringify(payload) });
    else await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/items/`, { method: "POST", body: JSON.stringify(payload) });
    setModal(false);
    await load();
  } catch (error) {
    errorEl.hidden = false; errorEl.textContent = error.data?.detail || error.message;
  } finally {
    saveBtn.disabled = false;
  }
}

async function handleDelete(itemId, { fromModal = false } = {}) {
  const item = items.find(i => i.id === itemId);
  if (!item) return;
  if (!(await confirmDialog({ kicker: "Permanent action", title: `Delete “${item.title}”?`, message: "This grade item cannot be recovered.", confirmLabel: "Delete grade", danger: true }))) return;
  try {
    await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/items/${encodeURIComponent(itemId)}/`, { method: "DELETE" });
    if (fromModal) setModal(false);
    await load();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function closeAllMenus(exceptId) {
  document.querySelectorAll(".grades-item-menu").forEach(menu => {
    if (menu.dataset.gradeMenu === exceptId) return;
    menu.hidden = true;
    menu.previousElementSibling?.setAttribute("aria-expanded", "false");
  });
}

document.addEventListener("click", event => {
  const target = event.target;

  const trigger = target.closest("[data-grade-menu-trigger]");
  if (trigger) {
    const menu = trigger.nextElementSibling;
    const willOpen = menu.hidden;
    closeAllMenus(willOpen ? menu.dataset.gradeMenu : null);
    menu.hidden = !willOpen;
    trigger.setAttribute("aria-expanded", String(willOpen));
    return;
  }
  if (!target.closest(".grades-item-menu-wrap")) closeAllMenus(null);

  const editBtn = target.closest("[data-grade-edit]");
  if (editBtn) { closeAllMenus(null); openEditModal(editBtn.dataset.gradeEdit); return; }

  const deleteBtn = target.closest("[data-grade-delete]");
  if (deleteBtn) { closeAllMenus(null); handleDelete(deleteBtn.dataset.gradeDelete); return; }

  if (target.closest("[data-close-grade-form]") || target === byId("grades-form-backdrop")) setModal(false);
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && byId("grades-form-backdrop") && !byId("grades-form-backdrop").hidden) setModal(false);
});

async function load() {
  try {
    const data = await apiRequest(`/api/courses/${encodeURIComponent(courseId)}/grades/`);
    items = data.items || [];
    grade = data.grade;
    renderSummary();
    renderBreakdown();
    populateWhatIfSelect();
    renderGradebook();
    byId("course-grades-status").hidden = true;
    byId("course-grades-error").hidden = true;
    byId("course-grades-content").hidden = false;
  } catch (error) {
    byId("course-grades-status").hidden = true;
    byId("course-grades-error").hidden = false;
    byId("course-grades-error").querySelector("p").textContent = error.message;
  }
}

byId("grades-add-btn")?.addEventListener("click", openAddModal);
byId("grades-item-form")?.addEventListener("submit", saveItem);
byId("grades-item-delete")?.addEventListener("click", () => handleDelete(byId("grades-item-id").value, { fromModal: true }));
byId("grades-whatif-form")?.addEventListener("submit", runWhatIf);
byId("grades-filter-category")?.addEventListener("change", event => { filterCategory = event.target.value; renderGradebook(); });
byId("grades-sort")?.addEventListener("change", event => { sortMode = event.target.value; renderGradebook(); });
byId("grades-goal-target")?.addEventListener("change", event => renderGoal(event.target.value));
byId("course-grades-error")?.querySelector("button")?.addEventListener("click", load);

if (courseId) { initCourseHeader(courseId); load(); }
