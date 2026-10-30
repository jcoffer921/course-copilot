import { initNavigation } from "./core/navigation.js";

initNavigation();

const dropzone = document.querySelector("[data-faculty-dropzone]");
const fileInput = document.querySelector("[data-faculty-file]");
const filename = document.querySelector("[data-faculty-filename]");
const sendToCora = document.querySelector("[data-send-to-cora]");
const sessionStorageKey = "ontrack.facultySession";

function parseCsvLine(line) {
  const values = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && quoted && line[index + 1] === '"') { value += '"'; index += 1; }
    else if (character === '"') quoted = !quoted;
    else if (character === "," && !quoted) { values.push(value.trim()); value = ""; }
    else value += character;
  }
  values.push(value.trim());
  return values;
}

async function buildTemporarySession(file) {
  const state = {
    activeFile: { name: file.name, uploadedAt: new Date().toISOString() },
    detectedColumns: [], majors: [], rowCount: 0, chatMessages: [], generatedPlan: null,
  };
  if (/\.csv$/i.test(file.name)) {
    const lines = (await file.text()).split(/\r?\n/).filter(line => line.trim());
    state.detectedColumns = lines.length ? parseCsvLine(lines[0]) : [];
    state.rowCount = Math.max(0, lines.length - 1);
    const majorIndex = state.detectedColumns.findIndex(column => /^(major|program|degree)$/i.test(column));
    if (majorIndex >= 0) {
      state.majors = [...new Set(lines.slice(1).map(line => parseCsvLine(line)[majorIndex]?.trim()).filter(Boolean))].slice(0, 12);
    }
  }
  sessionStorage.setItem(sessionStorageKey, JSON.stringify(state));
}

async function showSelectedFile(file) {
  if (!file || !filename) return;
  const validExtension = /\.(xlsx|csv)$/i.test(file.name);
  const validSize = file.size <= 10 * 1024 * 1024;
  filename.textContent = validExtension && validSize
    ? `${file.name} selected · ready to upload`
    : validExtension
      ? "This file is larger than the 10 MB limit."
      : "Choose an .xlsx or .csv file.";
  filename.classList.toggle("is-error", !validExtension || !validSize);
  if (sendToCora) sendToCora.hidden = !validExtension || !validSize;
  if (validExtension && validSize) await buildTemporarySession(file);
}

if (dropzone && fileInput) {
  fileInput.addEventListener("change", () => showSelectedFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach(eventName => dropzone.addEventListener(eventName, event => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach(eventName => dropzone.addEventListener(eventName, event => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
  }));
  dropzone.addEventListener("drop", event => {
    const file = event.dataTransfer.files[0];
    showSelectedFile(file);
  });
}
