const button = document.getElementById("google-auth-button");

button?.addEventListener("click", event => {
  if (button.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
    return;
  }
  button.setAttribute("aria-disabled", "true");
  button.classList.add("is-loading");
  const label = button.querySelector("span");
  if (label) label.textContent = "Connecting…";
});
