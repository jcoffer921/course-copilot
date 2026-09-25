import { initNavigation } from "./core/navigation.js";

initNavigation();

const dropzone = document.querySelector("[data-faculty-dropzone]");
const fileInput = document.querySelector("[data-faculty-file]");
const filename = document.querySelector("[data-faculty-filename]");

function showSelectedFile(file) {
  if (!file || !filename) return;
  const validExtension = /\.(xlsx|csv)$/i.test(file.name);
  const validSize = file.size <= 10 * 1024 * 1024;
  filename.textContent = validExtension && validSize
    ? `${file.name} selected · ready to upload`
    : validExtension
      ? "This file is larger than the 10 MB limit."
      : "Choose an .xlsx or .csv file.";
  filename.classList.toggle("is-error", !validExtension || !validSize);
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
