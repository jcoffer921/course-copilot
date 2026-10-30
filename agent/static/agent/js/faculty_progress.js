// Plain-language wording for waiting and failure states. No DOM, no imports.

export const SLOW_AFTER_SECONDS = 8;
export const VERY_SLOW_AFTER_SECONDS = 90;

export function formatElapsed(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  return `${minutes}m ${String(whole % 60).padStart(2, "0")}s`;
}

export function workingMessage(elapsedSeconds) {
  if (elapsedSeconds >= VERY_SLOW_AFTER_SECONDS) {
    return "This is taking longer than usual. You can keep waiting, or reload the page and try again.";
  }
  if (elapsedSeconds >= SLOW_AFTER_SECONDS) return `Still working, ${formatElapsed(elapsedSeconds)}`;
  return "Cora is drafting your plan";
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// A problem with the chosen file that can be reported before anything is uploaded, or null.
export function fileProblem(file) {
  if (!file) return "No file was selected.";
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
    return `"${file.name}" isn't an Excel file. Choose a .xlsx or .xlsm requirements file.`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  return null;
}

// What to tell the faculty member when reading a requirements file fails.
export function describeImportError(error) {
  const status = error?.status;
  if (!status) return "Couldn't reach the server. Check your connection and try again.";
  if (status === 400) return error.message || "That file couldn't be read.";
  if (status === 401 || status === 403) return "Your session expired. Reload the page and sign in again.";
  if (status === 413) return "That file is too large.";
  if (status === 429) return "You've reached today's request limit. Try again tomorrow.";
  if (status >= 500) return "The service had a problem reading this file. Try again in a moment.";
  return error.message || "Import failed.";
}

export const HEADER_MAX_LENGTH = 160;

// One trimmed line of visible text. Mirrors agent/services/export_header.py so the dialog's live
// preview shows exactly what the server will save.
export function normalizeHeaderLine(value) {
  if (typeof value !== "string") return "";
  const visible = Array.from(value, character => (/\s/.test(character) ? " " : /\p{C}/u.test(character) ? "" : character)).join("");
  const oneLine = visible.split(/\s+/).filter(Boolean).join(" ");
  return Array.from(oneLine).slice(0, HEADER_MAX_LENGTH).join("").trimEnd();
}
