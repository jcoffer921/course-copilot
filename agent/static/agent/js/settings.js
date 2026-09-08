import { apiRequest } from "./core/api.js";
import { promptDialog } from "./core/dialogs.js";
import { initNavigation } from "./core/navigation.js";
import { showToast } from "./core/toast.js";

initNavigation();
const $ = id => document.getElementById(id);
let profile = null;
let snapshot = null;

function friendlyError(error) {
  if (error?.status === 400) return "Check the highlighted settings and try again.";
  if (error?.status === 409) return "That change conflicts with an existing account setting.";
  return "We couldn't save your changes. Please try again.";
}

function formatBytes(bytes) {
  if (!bytes) return "0 bytes";
  const units = ["bytes", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function setText(id, value) { if ($(id)) $(id).textContent = value; }
function setValue(id, value) { if ($(id)) $(id).value = value ?? ""; }
function selectedDays() { return [...document.querySelectorAll(".settings-days input:checked")].map(input => Number(input.value)); }
function selectedDuration() { return Number(document.querySelector('input[name="duration"]:checked')?.value || profile?.preferred_session_minutes); }

function currentState() {
  return {
    display_name: $("settings-display-name")?.value.trim(),
    username: $("settings-username")?.value.trim(),
    bio: $("settings-bio")?.value.trim(),
    university: $("settings-university")?.value.trim(),
    major: $("settings-major")?.value.trim(),
    graduation_year: $("settings-graduation-year")?.value ? Number($("settings-graduation-year").value) : null,
    timezone: $("settings-timezone")?.value,
    preferred_session_minutes: selectedDuration(),
    available_study_days: selectedDays(),
    reminder_lead_minutes: Number($("settings-reminder")?.value ?? profile?.reminder_lead_minutes),
    notifications_enabled: $("settings-notifications")?.checked,
    email_notifications_enabled: $("settings-notifications-email")?.checked,
    study_reminder_time: $("settings-reminder-time")?.value,
  };
}

function relevantState() {
  const state = currentState();
  if ($("profile-form")) return {
    display_name: state.display_name, username: state.username, bio: state.bio,
    university: state.university, major: state.major, graduation_year: state.graduation_year,
    timezone: state.timezone,
  };
  if ($("preferences-form")) return { preferred_session_minutes: state.preferred_session_minutes, available_study_days: state.available_study_days, reminder_lead_minutes: state.reminder_lead_minutes };
  if ($("notifications-form")) return { notifications_enabled: state.notifications_enabled, email_notifications_enabled: state.email_notifications_enabled, study_reminder_time: state.study_reminder_time };
  return {};
}

function updateDirtyState() {
  if (!snapshot) return;
  const dirty = JSON.stringify(relevantState()) !== JSON.stringify(snapshot);
  const prefix = $("profile-form") ? "profile" : $("preferences-form") ? "preferences" : $("notifications-form") ? "notifications" : null;
  if (!prefix) return;
  $(`${prefix}-save`).disabled = !dirty;
  $(`${prefix}-cancel`).disabled = !dirty;
}

function fill(data) {
  profile = data;
  setValue("settings-display-name", data.display_name);
  setValue("settings-username", data.username);
  setValue("settings-bio", data.bio);
  setValue("settings-university", data.university);
  setValue("settings-major", data.major);
  setValue("settings-graduation-year", data.graduation_year);
  setValue("settings-email-input", data.email);
  setText("profile-identity-name", data.display_name);
  setText("profile-identity-email", data.email);
  setText("account-email", data.email);
  setText("google-account-label", data.email);
  setValue("settings-timezone", data.timezone);
  setValue("settings-notification-timezone", data.timezone);
  setValue("settings-reminder", data.reminder_lead_minutes);
  setValue("settings-reminder-time", data.study_reminder_time || "09:00");
  setText("settings-bio-count", (data.bio || "").length);
  if ($("settings-notifications")) $("settings-notifications").checked = data.notifications_enabled;
  if ($("settings-notifications-email")) $("settings-notifications-email").checked = data.email_notifications_enabled;
  document.querySelectorAll('.settings-days input').forEach(input => { input.checked = data.available_study_days.includes(Number(input.value)); });
  document.querySelector(`input[name="duration"][value="${data.preferred_session_minutes}"]`)?.click();

  setText("summary-member", new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(new Date(`${data.member_since}T00:00:00`)));
  setText("summary-courses", data.courses_enrolled);
  setText("summary-quizzes", data.quizzes_completed);
  setText("summary-streak", `${data.current_streak} ${data.current_streak === 1 ? "day" : "days"}`);
  setText("material-count", data.material_file_count);
  setText("storage-total", formatBytes(data.material_storage_bytes));
  if ($("google-identity-state")) {
    $("google-identity-state").textContent = data.google_identity_connected ? "Connected" : "Not connected";
    $("google-identity-state").classList.toggle("connected", data.google_identity_connected);
  }
  // Deadlines always live in OnTrack regardless of this connection — Google
  // Calendar is an optional mirror of them. "Needs reconnecting" (grant
  // failed after a prior connection) reads very differently from "Not
  // connected" (never set up) — collapsing them into one status made a
  // routine re-consent look like OnTrack losing something.
  if ($("calendar-state")) {
    $("calendar-state").textContent = data.calendar_connected
      ? "Connected"
      : data.calendar_connection_lapsed ? "Needs reconnecting" : "Not connected";
    $("calendar-state").classList.toggle("connected", data.calendar_connected);
  }
  if ($("calendar-connect")) {
    $("calendar-connect").hidden = data.calendar_connected;
    $("calendar-connect").textContent = data.calendar_connection_lapsed ? "Reconnect" : "Connect";
  }
  if ($("calendar-disconnect")) $("calendar-disconnect").hidden = !data.calendar_connected;
  snapshot = relevantState();
  updateDirtyState();
}

async function load() {
  $("settings-loading").hidden = false;
  $("settings-error").hidden = true;
  $("settings-content").hidden = true;
  try {
    fill(await apiRequest("/api/profile/"));
    $("settings-loading").hidden = true;
    $("settings-content").hidden = false;
    const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
    if (target) requestAnimationFrame(() => { target.scrollIntoView({ block: "center" }); target.focus({ preventScroll: true }); });
  } catch (error) {
    $("settings-loading").hidden = true;
    $("settings-error").hidden = false;
    $("settings-error").querySelector("p").textContent = "We couldn't load your settings. Please try again.";
  }
}

async function save(body, errorId, successMessage, submitButton) {
  const errorNode = $(errorId);
  errorNode.hidden = true;
  const original = submitButton.textContent;
  submitButton.disabled = true;
  submitButton.textContent = "Saving…";
  try {
    fill(await apiRequest("/api/profile/", { method: "PATCH", body: JSON.stringify(body) }));
    $("settings-status").textContent = successMessage;
    showToast(successMessage);
  } catch (error) {
    errorNode.textContent = friendlyError(error);
    errorNode.hidden = false;
  } finally {
    submitButton.textContent = original;
    updateDirtyState();
  }
}

$("profile-form")?.addEventListener("submit", event => {
  event.preventDefault();
  save({
    display_name: $("settings-display-name").value.trim(),
    username: $("settings-username").value.trim(),
    bio: $("settings-bio").value.trim(),
    university: $("settings-university").value.trim(),
    major: $("settings-major").value.trim(),
    graduation_year: $("settings-graduation-year").value ? Number($("settings-graduation-year").value) : null,
    timezone: $("settings-timezone").value,
  }, "profile-error", "Profile updated.", $("profile-save"));
});
$("preferences-form")?.addEventListener("submit", event => {
  event.preventDefault();
  save({ preferred_session_minutes: selectedDuration(), reminder_lead_minutes: Number($("settings-reminder").value), available_study_days: selectedDays() }, "preferences-error", "Preferences saved.", $("preferences-save"));
});
$("notifications-form")?.addEventListener("submit", event => {
  event.preventDefault();
  save({ notifications_enabled: $("settings-notifications").checked, email_notifications_enabled: $("settings-notifications-email").checked, study_reminder_time: $("settings-reminder-time").value }, "notifications-error", "Notification settings updated.", $("notifications-save"));
});

document.querySelectorAll(".settings-form input, .settings-form select, .settings-form textarea, #preferences-form input, #preferences-form select, #notifications-form input, #notifications-form select").forEach(control => {
  control.addEventListener("input", updateDirtyState);
  control.addEventListener("change", updateDirtyState);
});
$("settings-bio")?.addEventListener("input", event => setText("settings-bio-count", event.target.value.length));

for (const prefix of ["profile", "preferences", "notifications"]) {
  $(`${prefix}-cancel`)?.addEventListener("click", () => fill(profile));
}
$("settings-retry")?.addEventListener("click", load);

$("delete-open")?.addEventListener("click", async () => {
  const confirmation = await promptDialog({
    kicker: "Permanent action",
    title: "Delete your OnTrack account?",
    message: "This permanently removes your profile, courses, materials, study history, plans, and connections. This cannot be undone.",
    inputLabel: "Type DELETE MY ACCOUNT to confirm",
    requiredValue: "DELETE MY ACCOUNT",
    confirmLabel: "Delete my account",
    danger: true,
  });
  if (!confirmation) return;
  try {
    await apiRequest("/api/profile/", { method: "DELETE", body: JSON.stringify({ confirmation }) });
    window.location.assign("/accounts/login/");
  } catch (error) {
    showToast("We couldn't delete your account. Please try again.", "error");
  }
});

load();
