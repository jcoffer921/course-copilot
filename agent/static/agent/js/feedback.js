import { getCsrfToken } from "./core/csrf.js";
import { initNavigation } from "./core/navigation.js";

initNavigation();

function updatePrivacyCopy() {
  const anonymous = document.querySelector("#feedback-anonymous");
  const privacyCopy = document.querySelector("#feedback-privacy-copy");
  if (!anonymous || !privacyCopy) return;
  privacyCopy.textContent = anonymous.checked
    ? "Your account and current page will not be attached to this feedback."
    : "Your OnTrack account will be attached so we can follow up with you.";
}

document.addEventListener("change", event => {
  if (event.target.matches("#feedback-anonymous")) updatePrivacyCopy();
});

document.addEventListener("submit", async event => {
  if (!event.target.matches("#feedback-page-form")) return;
  event.preventDefault();
  const form = event.target;
  const anonymous = form.querySelector("#feedback-anonymous");
  const error = document.querySelector("#feedback-page-error");
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  submit.textContent = "Sending…";
  error.textContent = "";
  try {
    const response = await fetch("/api/feedback/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({
        category: form.elements.category.value,
        message: form.elements.message.value,
        anonymous: anonymous.checked,
        page: anonymous.checked ? "" : `${location.pathname}${location.search}`.slice(0, 255),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "We couldn't send that feedback. Please try again.");
    form.reset();
    anonymous.checked = true;
    updatePrivacyCopy();
    document.body.classList.add("feedback-submitted");
    document.querySelector("#feedback-success-panel a")?.focus();
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    submit.disabled = false;
    submit.textContent = "Send feedback";
  }
});

updatePrivacyCopy();
window.setTimeout(updatePrivacyCopy, 0);
