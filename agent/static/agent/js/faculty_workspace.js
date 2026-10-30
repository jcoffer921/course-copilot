const root = document.getElementById("fw-root");

const picker = root?.querySelector("[data-fw-program-picker]");
picker?.addEventListener("change", () => {
  const url = new URL(window.location.href);
  if (picker.value) url.searchParams.set("program", picker.value);
  else url.searchParams.delete("program");
  window.location.assign(url);
});
