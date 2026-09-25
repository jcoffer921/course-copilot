import { apiRequest } from "./api.js";
import { showToast } from "./toast.js";

const root = document.getElementById("site-notifications");
const state = { open: false, busy: false };
const byId = (id) => document.getElementById(id);

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("ot-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", `#ot-icon-${name}`);
  svg.append(use);
  return svg;
}

function shortDate(value) {
  if (!value) return "";
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeAgo(value) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return "";
  const minutes = Math.max(0, Math.round((Date.now() - timestamp.getTime()) / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function itemPresentation(item) {
  if (item.kind === "cora_message") return { icon: "cora", label: "Cora message", action: "Open conversation" };
  if (item.kind === "study_reminder") return { icon: "study", label: "Study reminder", action: "Start studying" };
  return { icon: "calendar", label: item.due_date ? `Due ${shortDate(item.due_date)}` : "Deadline update", action: "View in calendar" };
}

function render(data) {
  const count = data.unread_count || 0;
  const items = data.notifications || [];
  const badge = byId("site-notification-badge");
  badge.textContent = count > 9 ? "9+" : String(count || "");
  badge.hidden = !count;
  byId("site-notification-summary").textContent = count ? `${count} unread update${count === 1 ? "" : "s"}` : "You’re all caught up";
  byId("site-notifications-read").hidden = !count;
  byId("site-notifications-list").replaceChildren(...items.map((item) => {
    const presentation = itemPresentation(item);
    const row = document.createElement("li");
    if (!item.read) row.classList.add("unread");
    const itemIcon = document.createElement("span");
    itemIcon.className = "site-notification-item-icon";
    itemIcon.append(icon(presentation.icon));
    const copy = document.createElement("div");
    copy.className = "site-notification-copy";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const body = document.createElement("span");
    body.textContent = item.body || "OnTrack update";
    const meta = document.createElement("small");
    meta.textContent = [presentation.label, timeAgo(item.created_at)].filter(Boolean).join(" · ");
    const action = document.createElement("a");
    action.className = "site-notification-view";
    action.href = item.action_url || "/dashboard/";
    action.textContent = presentation.action;
    copy.append(title, body, meta, action);
    row.append(itemIcon, copy);
    if (!item.read) {
      const read = document.createElement("button");
      read.type = "button";
      read.className = "site-notification-read-one";
      read.dataset.notificationId = item.id;
      read.setAttribute("aria-label", `Mark ${item.title} as read`);
      read.textContent = "Mark read";
      row.append(read);
    }
    return row;
  }));
  const status = byId("site-notifications-status");
  status.replaceChildren();
  status.hidden = items.length > 0;
  if (!items.length) status.append(icon("check"), document.createTextNode("No new notifications. You’re all caught up."));
}

async function loadNotifications({ quiet = false } = {}) {
  const status = byId("site-notifications-status");
  if (!quiet) {
    status.hidden = false;
    status.replaceChildren(Object.assign(document.createElement("span"), { className: "site-notification-spinner" }), document.createTextNode("Loading notifications…"));
  }
  try {
    render(await apiRequest("/api/notifications/"));
  } catch {
    status.hidden = false;
    status.replaceChildren(document.createTextNode("Notifications aren’t available right now."));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Try again";
    retry.addEventListener("click", () => loadNotifications());
    status.append(retry);
  }
}

function setOpen(open, restoreFocus = true) {
  state.open = open;
  byId("site-notification-popover").hidden = !open;
  byId("site-notification-scrim").hidden = !open;
  const toggle = byId("site-notification-toggle");
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-label", open ? "Close notifications" : "Open notifications");
  document.body.classList.toggle("site-notifications-open", open);
  if (open) {
    loadNotifications({ quiet: true });
    byId("site-notification-close").focus();
  } else if (restoreFocus) {
    toggle.focus();
  }
}

async function markRead(ids, button) {
  if (state.busy) return;
  state.busy = true;
  if (button) button.disabled = true;
  try {
    const data = await apiRequest("/api/notifications/read/", { method: "PATCH", body: JSON.stringify(ids ? { ids } : {}) });
    render(data);
  } catch {
    showToast("Couldn’t update notifications. Please try again.", "error");
    if (button) button.disabled = false;
  } finally {
    state.busy = false;
  }
}

function bind() {
  document.addEventListener("click", (event) => {
    if (event.target.closest("#site-notification-toggle")) return setOpen(!state.open);
    if (event.target.closest("#site-notification-close, #site-notification-scrim")) return setOpen(false);
    if (event.target.closest("#site-notifications-read")) return markRead(null, event.target.closest("#site-notifications-read"));
    const readOne = event.target.closest("[data-notification-id]");
    if (readOne) return markRead([Number(readOne.dataset.notificationId)], readOne);
    if (state.open && !event.target.closest("#site-notification-popover")) setOpen(false, false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.open) {
      event.preventDefault();
      setOpen(false);
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadNotifications({ quiet: true });
  });
}

if (root) {
  bind();
  loadNotifications();
  window.setInterval(() => loadNotifications({ quiet: true }), 60_000);
}
