import { apiRequest } from "./core/api.js";
import { confirmDialog } from "./core/dialogs.js";
import { showToast } from "./core/toast.js";
import { runImportFlow } from "./faculty_import_flow.js";
import { pluralize } from "./faculty_plan_model.js";

const root = document.getElementById("fp-root");

function el(tag, { className, text } = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

if (root) {
  const apiBase = root.dataset.apiBase;
  const rows = [...root.querySelectorAll("[data-fp-row]")];
  const detailEmpty = root.querySelector("[data-fp-detail-empty]");
  const detailBody = root.querySelector("[data-fp-detail-body]");
  const importInput = root.querySelector("[data-fp-import-input]");
  let selected = null;

  async function selectRow(row) {
    rows.forEach(item => item.classList.toggle("is-selected", item === row));
    selected = { id: row.dataset.requirementId, name: row.dataset.programName };
    try {
      const { program } = await apiRequest(`${apiBase}${selected.id}/`);
      root.querySelector("[data-fp-name]").textContent = program.program_name || "Unnamed program";
      const groups = program.categories.length;
      const courses = program.categories.reduce((sum, category) => sum + category.course_count, 0);
      root.querySelector("[data-fp-meta]").textContent =
        `${program.source_filename || "Imported file"} · ${pluralize(groups, "group")} · ${pluralize(courses, "course")}`;
      const list = root.querySelector("[data-fp-categories]");
      list.replaceChildren(...program.categories.map(category => {
        const item = el("li");
        item.append(el("strong", { text: category.name || "Unnamed group" }), el("span", { text: ` ${category.credits_required} credits, ${pluralize(category.course_count, "course")}` }));
        return item;
      }));
      if (!program.categories.length) list.append(el("li", { className: "fs-empty", text: "This program has no requirement groups." }));
      root.querySelector("[data-fp-checks]").textContent =
        `Prerequisites resolved: ${program.checks.prerequisites_resolved} of ${program.checks.prerequisites_total}`;
      detailEmpty.hidden = true;
      detailBody.hidden = false;
    } catch (error) {
      showToast(error.message || "Could not load that program.", "error");
    }
  }

  rows.forEach(row => {
    row.addEventListener("click", event => { if (!event.target.closest("a")) selectRow(row); });
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        if (event.target.closest("a")) return;
        event.preventDefault();
        selectRow(row);
      }
    });
  });

  async function startImport(file) {
    if (!file) return;
    if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
      showToast("Choose an Excel file (.xlsx or .xlsm).", "error");
      return;
    }
    try {
      const confirmed = await runImportFlow({ file, importUrl: root.dataset.importUrl, confirmUrl: root.dataset.confirmUrl });
      if (confirmed) {
        showToast(`Saved ${confirmed.program_name || "program"}.`, "success");
        window.location.reload();
      }
    } catch (error) {
      showToast(error.message || "Import failed.", "error");
    }
  }

  importInput.addEventListener("change", () => {
    const [file] = importInput.files;
    importInput.value = "";
    startImport(file);
  });
  document.querySelectorAll("[data-fp-import]").forEach(button => button.addEventListener("click", () => importInput.click()));
  root.querySelector("[data-fp-reimport]")?.addEventListener("click", () => importInput.click());

  root.querySelector("[data-fp-delete]")?.addEventListener("click", async () => {
    if (!selected) return;
    const ok = await confirmDialog({
      title: "Delete this program?",
      message: `"${selected.name || "This program"}" will be removed permanently. Draft plans already exported are not affected.`,
      confirmLabel: "Delete program",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiRequest(`${apiBase}${selected.id}/`, { method: "DELETE", body: JSON.stringify({ confirm: true }) });
      window.location.reload();
    } catch (error) {
      showToast(error.message || "Could not delete that program.", "error");
    }
  });
}
