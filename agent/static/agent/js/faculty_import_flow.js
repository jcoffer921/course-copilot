import { apiRequest } from "./core/api.js";
import { getCsrfToken } from "./core/csrf.js";
import { pluralize } from "./faculty_plan_model.js";
import { describeImportError, fileProblem, formatBytes, formatElapsed } from "./faculty_progress.js";

function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  for (const child of children) node.append(child);
  return node;
}

const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));

function actionButton(action) {
  return el("button", {
    className: `fs-btn${action.primary ? " is-primary" : ""}${action.danger ? " is-danger" : ""}`,
    text: action.label,
    attrs: { type: "button" },
  });
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
      const button = actionButton(action);
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

// A modal that shows where a slow step is up to, how long it has run, and, if it fails, why. The
// failure stays on screen until the faculty member chooses what to do about it.
function createProgressDialog({ title, stages, file }) {
  const dialog = el("dialog", { className: "fs-dialog fs-progress", attrs: { "aria-labelledby": "fs-progress-title", "aria-busy": "true" } });
  const stageNodes = stages.map(label => el("li", { attrs: { "data-state": "pending" } }, [
    el("span", { className: "fs-stage-mark", attrs: { "aria-hidden": "true" } }),
    el("span", { text: label }),
  ]));
  const status = el("p", { className: "fs-progress-status", attrs: { role: "status", "aria-live": "polite" } });
  const problem = el("p", { className: "fs-progress-error", attrs: { role: "alert" } });
  problem.hidden = true;
  const footer = el("footer", { className: "fs-dialog-actions" });
  dialog.append(el("h2", { text: title, attrs: { id: "fs-progress-title" } }));
  if (file) dialog.append(el("p", { className: "fs-progress-file", text: `${file.name} · ${formatBytes(file.size)}` }));
  dialog.append(el("ol", { className: "fs-stages" }, stageNodes), status, problem, footer);
  document.body.append(dialog);
  dialog.showModal();

  let timer = null;
  let current = 0;
  let onDismiss = null;
  dialog.addEventListener("cancel", event => { event.preventDefault(); onDismiss?.(); });

  const mark = (index, state) => { stageNodes[index].dataset.state = state; };

  const ui = {
    get stage() { return current; },
    setStage(index) {
      current = index;
      stageNodes.forEach((_, position) => mark(position, position < index ? "done" : position === index ? "active" : "pending"));
      problem.hidden = true;
      dialog.setAttribute("aria-busy", "true");
    },
    completeAll() {
      stageNodes.forEach((_, position) => mark(position, "done"));
      status.textContent = "Done";
      dialog.setAttribute("aria-busy", "false");
    },
    startTimer(label) {
      ui.stopTimer();
      const started = Date.now();
      const tick = () => { status.textContent = `${label}… ${formatElapsed((Date.now() - started) / 1000)}`; };
      tick();
      timer = window.setInterval(tick, 1000);
    },
    stopTimer() {
      if (timer) window.clearInterval(timer);
      timer = null;
    },
    // Buttons for the working state. `cancel` (optional) is also bound to Escape.
    setActions(actions, cancel) {
      footer.replaceChildren(...actions.map(action => {
        const button = actionButton(action);
        button.addEventListener("click", action.onClick);
        return button;
      }));
      onDismiss = cancel || null;
      footer.querySelector("button")?.focus();
    },
    // Shows the failure and waits for the faculty member to pick an action; resolves to its value.
    fail(index, message, actions) {
      ui.stopTimer();
      mark(index, "failed");
      status.textContent = "";
      problem.textContent = message;
      problem.hidden = false;
      dialog.setAttribute("aria-busy", "false");
      return new Promise(resolve => {
        onDismiss = () => resolve(null);
        footer.replaceChildren(...actions.map(action => {
          const button = actionButton(action);
          button.addEventListener("click", () => resolve(action.value));
          return button;
        }));
        (footer.querySelector(".is-primary") || footer.querySelector("button"))?.focus();
      });
    },
    close() {
      ui.stopTimer();
      if (dialog.open) dialog.close();
      dialog.remove();
    },
  };
  return ui;
}

// POSTs the file with XMLHttpRequest (unlike fetch it reports when the upload itself has finished),
// so the dialog's "Uploading" step ends when the file is sent, not when the model is done reading it.
function uploadRequirements({ file, url, signal, onUploaded }) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", url);
    request.setRequestHeader("Accept", "application/json");
    request.setRequestHeader("X-CSRFToken", getCsrfToken());
    request.upload.addEventListener("load", () => onUploaded?.());
    request.addEventListener("load", () => {
      let data = null;
      try { data = JSON.parse(request.responseText); } catch { /* non-JSON body */ }
      if (request.status >= 200 && request.status < 300) return resolve(data);
      const error = new Error(data?.detail || `Request failed with status ${request.status}.`);
      error.status = request.status;
      error.data = data;
      reject(error);
    });
    request.addEventListener("error", () => reject(new TypeError("Network error")));
    request.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    signal?.addEventListener("abort", () => request.abort(), { once: true });
    const body = new FormData();
    body.append("file", file);
    request.send(body);
  });
}

function reviewBody(requirements) {
  const categories = requirements.categories || [];
  const list = el("ul", { className: "fs-dialog-list" }, categories.map(category =>
    el("li", {}, [
      el("strong", { text: category.name || "Unnamed group" }),
      el("span", { text: ` ${category.credits_required || 0} credits required, ${pluralize((category.courses || []).length, "course")}` }),
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
    el("p", { text: `A program named "${existing.program_name}" for catalog year ${existing.catalog_year || "(none)"} already exists with ${pluralize(existing.category_count, "group")} and ${pluralize(existing.course_count, "course")}.` }),
    el("p", { text: "Overwriting replaces its requirements with the file you just imported." }),
  ]);
}

const FAILURE_ACTIONS = {
  close: { label: "Close", value: null },
  other: { label: "Choose another file", value: "other" },
  retry: { label: "Try again", value: "retry", primary: true },
};

// Reads the file into structured requirements. Resolves to the extracted payload, or null if the
// faculty member cancelled or gave up (after being shown why it failed).
async function extractWithProgress({ file, importUrl, onChooseAnother }) {
  const ui = createProgressDialog({ title: "Importing requirements", stages: ["Uploading file", "Reading requirements", "Ready to review"], file });
  try {
    const problem = fileProblem(file);
    if (problem) {
      const choice = await ui.fail(0, problem, [FAILURE_ACTIONS.close, { ...FAILURE_ACTIONS.other, primary: true }]);
      if (choice === "other") onChooseAnother?.();
      return null;
    }
    for (;;) {
      const controller = new AbortController();
      ui.setStage(0);
      ui.startTimer("Uploading");
      ui.setActions([{ label: "Cancel", onClick: () => controller.abort() }], () => controller.abort());
      try {
        const extracted = await uploadRequirements({
          file,
          url: importUrl,
          signal: controller.signal,
          onUploaded: () => { ui.setStage(1); ui.startTimer("Reading requirements"); },
        });
        ui.completeAll();
        await sleep(350);
        return extracted;
      } catch (error) {
        if (controller.signal.aborted) return null;
        const choice = await ui.fail(ui.stage, describeImportError(error), [FAILURE_ACTIONS.close, FAILURE_ACTIONS.other, FAILURE_ACTIONS.retry]);
        if (choice === "retry") continue;
        if (choice === "other") onChooseAnother?.();
        return null;
      }
    }
  } finally {
    ui.close();
  }
}

// Writes the confirmed requirements, asking before replacing an existing program. Resolves to the saved
// program_requirement, or null if the faculty member declined or gave up.
async function saveWithProgress({ requirements, sourceFilename, confirmUrl }) {
  const submit = overwrite => apiRequest(confirmUrl, {
    method: "POST",
    body: JSON.stringify({ confirm: true, requirements, source_filename: sourceFilename, overwrite }),
  });
  let overwrite = false;
  for (;;) {
    const ui = createProgressDialog({ title: "Saving program", stages: ["Saving program"] });
    try {
      ui.setStage(0);
      ui.startTimer("Saving");
      ui.setActions([]);
      try {
        const saved = await submit(overwrite);
        ui.completeAll();
        await sleep(350);
        return saved.program_requirement;
      } catch (error) {
        if (error.status === 409 && !overwrite) {
          ui.close();
          const choice = await openDialog({
            title: "Replace existing program?",
            body: conflictBody(error.data?.existing || {}),
            actions: [
              { label: "Cancel", value: null },
              { label: "Overwrite", value: "overwrite", danger: true, primary: true },
            ],
          });
          if (choice !== "overwrite") return null;
          overwrite = true;
          continue;
        }
        const choice = await ui.fail(0, describeImportError(error), [FAILURE_ACTIONS.close, FAILURE_ACTIONS.retry]);
        if (choice === "retry") continue;
        return null;
      }
    } finally {
      ui.close();
    }
  }
}

// Extracts a requirements file for review, then confirms it. Resolves to the confirmed
// program_requirement, or null if the faculty member cancels or gives up after a failure.
// `onChooseAnother` is called when they pick "Choose another file" so the page can reopen its picker.
export async function runImportFlow({ file, importUrl, confirmUrl, onChooseAnother }) {
  const extracted = await extractWithProgress({ file, importUrl, onChooseAnother });
  if (!extracted) return null;

  const decision = await openDialog({
    title: "Review imported requirements",
    body: reviewBody(extracted.requirements),
    actions: [
      { label: "Cancel", value: null },
      { label: "Confirm and save", value: "confirm", primary: true },
    ],
  });
  if (decision !== "confirm") return null;

  return saveWithProgress({ requirements: extracted.requirements, sourceFilename: extracted.source_filename, confirmUrl });
}
