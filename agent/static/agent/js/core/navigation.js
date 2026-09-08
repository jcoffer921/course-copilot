const TAB_ROUTES = {
  dashboard: "/dashboard/",
  deadlines: "/calendar/",
  chat: "/cora/",
  progress: "/study/",
  flashcards: "/study/",
  quiz: "/study/",
  grades: "/study/?view=grades",
  courses: "/courses/",
  settings: "/settings/",
};

export function routeForTab(tab) {
  return TAB_ROUTES[tab] || null;
}

export function navigateToTab(tab) {
  const route = routeForTab(tab);
  if (route) window.location.assign(route);
}

export function initNavigation() {
  const toggle = document.querySelector("[data-nav-toggle]");
  const sidebar = document.getElementById("app-sidebar");
  if (!toggle || !sidebar) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => window.setTimeout(initNavigation, 0), { once: true });
    }
    return;
  }
  if (toggle.dataset.navigationBound === "true") return;
  toggle.dataset.navigationBound = "true";
  const close = () => {
    sidebar.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  };
  toggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
    if (open) sidebar.querySelector("a")?.focus();
  });
  sidebar.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      close();
      toggle.focus();
    }
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 800) close();
  });
}

window.OnTrackNavigation = { routeForTab, navigateToTab, init: initNavigation };
