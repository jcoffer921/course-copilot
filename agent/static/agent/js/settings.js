import { apiRequest } from "./core/api.js";
import { initNavigation } from "./core/navigation.js";
import { showToast } from "./core/toast.js";

initNavigation();
const $ = id => document.getElementById(id);
let profile;
let lastFocus;

function message(error) {
  if (error?.data && typeof error.data === "object") return Object.values(error.data).flat().join(" ");
  return error?.message || "Something went wrong.";
}

function fill(data) {
  profile = data;
  $("settings-display-name").value = data.display_name || "";
  $("settings-email").textContent = data.email || "";
  $("settings-timezone").value = data.timezone;
  $("settings-duration").value = String(data.preferred_session_minutes);
  $("settings-reminder").value = String(data.reminder_lead_minutes);
  $("settings-reminder-time").value = data.study_reminder_time || "09:00";
  $("settings-notifications").checked = data.notifications_enabled;
  document.querySelectorAll(".settings-days input").forEach(input => { input.checked = data.available_study_days.includes(Number(input.value)); });
  $("calendar-state").textContent = data.calendar_connected ? "Google Calendar connected" : "Calendar not connected — optional";
  $("calendar-connect").hidden = data.calendar_connected;
  $("calendar-disconnect").hidden = !data.calendar_connected;
}

async function load() {
  $("settings-loading").hidden = false; $("settings-error").hidden = true; $("settings-content").hidden = true;
  try { fill(await apiRequest("/api/profile/")); $("settings-loading").hidden = true; $("settings-content").hidden = false; }
  catch (error) { $("settings-loading").hidden = true; $("settings-error").hidden = false; $("settings-error").querySelector("p").textContent = message(error); }
}

async function save(body, errorId) {
  const errorNode = $(errorId); errorNode.hidden = true;
  try {
    fill(await apiRequest("/api/profile/", { method: "PATCH", body: JSON.stringify(body) }));
    $("settings-status").textContent = "Settings saved."; showToast("Settings saved.");
  } catch (error) { errorNode.textContent = message(error); errorNode.hidden = false; }
}

$("profile-form")?.addEventListener("submit", event => { event.preventDefault(); save({ display_name: $("settings-display-name").value, timezone: $("settings-timezone").value }, "profile-error"); });
$("preferences-form")?.addEventListener("submit", event => {
  event.preventDefault();
  save({
    preferred_session_minutes: Number($("settings-duration").value), reminder_lead_minutes: Number($("settings-reminder").value),
    available_study_days: [...document.querySelectorAll(".settings-days input:checked")].map(input => Number(input.value)),
  }, "preferences-error");
});
$("notifications-form")?.addEventListener("submit", event => {
  event.preventDefault();
  save({
    notifications_enabled: $("settings-notifications").checked,
    study_reminder_time: $("settings-reminder-time").value,
  }, "notifications-error");
});
$("settings-retry")?.addEventListener("click", load);

function closeDialog() { $("delete-dialog").hidden = true; lastFocus?.focus(); }
$("delete-open")?.addEventListener("click", event => { lastFocus = event.currentTarget; $("delete-dialog").hidden = false; $("delete-dialog").querySelector("input").focus(); });
$("delete-cancel")?.addEventListener("click", closeDialog);
$("delete-dialog")?.addEventListener("click", event => { if (event.target === $("delete-dialog")) closeDialog(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("delete-dialog")?.hidden) closeDialog(); });

document.addEventListener("submit", async event => {
  const form = event.target.closest("[data-account-delete-form]"); if (!form) return;
  event.preventDefault(); const errorNode = form.querySelector("[data-account-delete-error]"); const button = form.querySelector("button[type='submit']");
  errorNode.hidden = true; button.disabled = true;
  try { await apiRequest("/api/profile/", { method: "DELETE", body: JSON.stringify({ confirmation: new FormData(form).get("confirmation") }) }); window.location.assign("/accounts/login/"); }
  catch (error) { errorNode.textContent = message(error); errorNode.hidden = false; button.disabled = false; }
});

load();
