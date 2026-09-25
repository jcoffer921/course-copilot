export function focusFirst(container) {
  container?.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")?.focus();
}

export function restoreFocus(element) {
  if (element && document.contains(element)) element.focus();
}

window.OnTrackModal = { focusFirst, restoreFocus };
