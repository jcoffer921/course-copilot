import { getCsrfToken } from "./csrf.js";

export async function apiRequest(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(options.method || "GET")) headers.set("X-CSRFToken", getCsrfToken());
  const response = await fetch(url, { credentials: "same-origin", ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const error = new Error(data?.detail || `Request failed with status ${response.status}.`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

window.OnTrackApi = { request: apiRequest };
