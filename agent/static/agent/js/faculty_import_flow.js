import { apiRequest } from "./core/api.js";

function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  for (const child of children) node.append(child);
  return node;
}

// Opens a modal <dialog>; resolves with the chosen action's value, or null if dismissed.
function openDialog({ title, body, actions }) {
  return new Promise(resolve => {
    const dialog = el("dialog", { className: "fs-dialog", attrs: { "aria-labelledby": "fs-dialog-title" } });
    let settled = false;
    const finish = value => {
      if (settled) return;
      settled = true;
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    const buttons = actions.map(action => {
      const button = el("button", {
        className: `fs-btn${action.primary ? " is-primary" : ""}${action.danger ? " is-danger" : ""}`,
        text: action.label,
        attrs: { type: "button" },
      });
      button.addEventListener("click", () => finish(action.value));
      return button;
    });
    dialog.append(
      el("h2", { text: title, attrs: { id: "fs-dialog-title" } }),
      body,
      el("footer", { className: "fs-dialog-actions" }, buttons),
    );
    dialog.addEventListener("cancel", event => { event.preventDefault(); finish(null); });
    document.body.append(dialog);
    dialog.showModal();
    (buttons.find((_, index) => actions[index].primary) || buttons[0])?.focus();
  });
}

function reviewBody(requirements) {
  const categories = requirements.categories || [];
  const list = el("ul", { className: "fs-dialog-list" }, categories.map(category =>
    el("li", {}, [
      el("strong", { text: category.name || "Unnamed group" }),
      el("span", { text: ` ${category.credits_required || 0} credits required, ${(category.courses || []).length} courses` }),
    ])));
  return el("div", { className: "fs-dialog-body" }, [
    el("p", { text: "Review what was read from the file. Cora plans only from these requirements." }),
    el("dl", { className: "fs-dialog-facts" }, [
      el("dt", { text: "Program" }), el("dd", { text: requirements.program_name || "Unnamed program" }),
      el("dt", { text: "Catalog year" }), el("dd", { text: requirements.catalog_year || "Not found in file" }),
      el("dt", { text: "Total credits" }), el("dd", { text: String(requirements.total_credits_required || 0) }),
    ]),
    categories.length ? list : el("p", { text: "No requirement groups were found in this file." }),
  ]);
}

function conflictBody(existing) {
  return el("div", { className: "fs-dialog-body" }, [
    el("p", { text: `A program named "${existing.program_name}" for catalog year ${existing.catalog_year || "(none)"} already exists with ${existing.category_count} groups and ${existing.course_count} courses.` }),
    el("p", { text: "Overwriting replaces its requirements with the file you just imported." }),
  ]);
}

// Extracts a requirements file for review, then confirms it. Resolves to the confirmed
// program_requirement, or null if the faculty member cancels. Network errors propagate.
export async function runImportFlow({ file, importUrl, confirmUrl }) {
  const upload = new FormData();
  upload.append("file", file);
  const { requirements, source_filename: sourceFilename } = await apiRequest(importUrl, { method: "POST", body: upload });

  const decision = await openDialog({
    title: "Review imported requirements",
    body: reviewBody(requirements),
    actions: [
      { label: "Cancel", value: null },
      { label: "Confirm and save", value: "confirm", primary: true },
    ],
  });
  if (decision !== "confirm") return null;

  const submit = ({ overwrite }) => apiRequest(confirmUrl, {
    method: "POST",
    body: JSON.stringify({ confirm: true, requirements, source_filename: sourceFilename, overwrite }),
  });

  try {
    const saved = await submit({ overwrite: false });
    return saved.program_requirement;
  } catch (error) {
    if (error.status !== 409) throw error;
    const overwrite = await openDialog({
      title: "Replace existing program?",
      body: conflictBody(error.data?.existing || {}),
      actions: [
        { label: "Cancel", value: null },
        { label: "Overwrite", value: "overwrite", danger: true, primary: true },
      ],
    });
    if (overwrite !== "overwrite") return null;
    const saved = await submit({ overwrite: true });
    return saved.program_requirement;
  }
}
