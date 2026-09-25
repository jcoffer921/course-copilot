const backdrop = document.querySelector("#ontrack-action-dialog");
const dialog = backdrop?.querySelector(".action-dialog");
const title = document.querySelector("#action-dialog-title");
const message = document.querySelector("#action-dialog-message");
const kicker = document.querySelector("#action-dialog-kicker");
const inputWrap = document.querySelector("#action-dialog-input-wrap");
const inputLabel = document.querySelector("#action-dialog-input-label");
const input = document.querySelector("#action-dialog-input");
const validation = document.querySelector("#action-dialog-validation");
const cancel = document.querySelector("#action-dialog-cancel");
const confirm = document.querySelector("#action-dialog-confirm");
let settle = null;
let previousFocus = null;

function close(value) {
  if (!settle) {
    backdrop.hidden = true;
    backdrop.classList.add("is-closed");
    backdrop.setAttribute("aria-hidden", "true");
    inputWrap.hidden = true;
    inputWrap.classList.add("is-closed");
    validation.hidden = true;
    validation.classList.add("is-closed");
    document.body.classList.remove("action-dialog-open");
    return;
  }
  const resolve = settle;
  settle = null;
  backdrop.hidden = true;
  backdrop.classList.add("is-closed");
  backdrop.setAttribute("aria-hidden", "true");
  document.body.classList.remove("action-dialog-open");
  previousFocus?.focus();
  resolve(value);
}

function open(options = {}) {
  if (!backdrop) return Promise.resolve(options.input ? null : false);
  if (settle) close(options.input ? null : false);
  previousFocus = document.activeElement;
  kicker.textContent = options.kicker || "Please confirm";
  title.textContent = options.title || "Confirm action";
  message.textContent = options.message || "";
  confirm.textContent = options.confirmLabel || "Continue";
  confirm.classList.toggle("danger", options.danger === true);
  inputWrap.hidden = !options.input;
  inputWrap.classList.toggle("is-closed", !options.input);
  validation.hidden = true;
  validation.classList.add("is-closed");
  input.value = options.defaultValue || "";
  inputLabel.textContent = options.inputLabel || "Enter a value";
  input.placeholder = options.placeholder || "";
  input.dataset.requiredValue = options.requiredValue || "";
  backdrop.hidden = false;
  backdrop.classList.remove("is-closed");
  backdrop.setAttribute("aria-hidden", "false");
  document.body.classList.add("action-dialog-open");
  window.dispatchEvent(new CustomEvent("ontrack:action-dialog-open"));
  queueMicrotask(() => (options.input ? input : confirm).focus());
  return new Promise(resolve => { settle = resolve; });
}

cancel?.addEventListener("click", () => close(inputWrap.hidden ? false : null));
confirm?.addEventListener("click", () => {
  if (!inputWrap.hidden) {
    const value = input.value.trim();
    const required = input.dataset.requiredValue;
    if (!value || (required && value !== required)) {
      validation.textContent = required ? `Type ${required} to continue.` : "Enter a value to continue.";
      validation.hidden = false;
      validation.classList.remove("is-closed");
      input.focus();
      return;
    }
    close(value);
    return;
  }
  close(true);
});
backdrop?.addEventListener("click", event => { if (event.target === backdrop) close(inputWrap.hidden ? false : null); });
input?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); confirm.click(); } });
document.addEventListener("keydown", event => {
  if (!backdrop || backdrop.hidden) return;
  if (event.key === "Escape") close(inputWrap.hidden ? false : null);
  if (event.key === "Tab") {
    const controls = [...dialog.querySelectorAll("button:not([disabled]),input:not([disabled])")].filter(el => !el.closest("[hidden]"));
    if (!controls.length) return;
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

export function confirmDialog(options) { return open({ ...options, input: false }); }
export function promptDialog(options) { return open({ ...options, input: true }); }
export function dismissDialog() { close(inputWrap?.hidden ? false : null); }

window.OnTrackDialogs = { confirm: confirmDialog, prompt: promptDialog, dismiss: dismissDialog };
