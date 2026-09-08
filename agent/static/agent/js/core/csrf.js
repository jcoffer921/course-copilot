export function getCsrfToken() {
  const pair = document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith("csrftoken="));
  return pair ? decodeURIComponent(pair.slice("csrftoken=".length)) : "";
}

window.OnTrackCsrf = { getToken: getCsrfToken };
