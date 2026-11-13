// No login: the traveler's own request IDs are remembered in this browser,
// so "My rides" shows only what this traveler posted.
const KEY = "airport-taxi.my-requests";

export function getMyRequestIds() {
  try {
    const ids = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(ids) ? ids : [];
  } catch {
    return [];
  }
}

export function rememberRequest(id) {
  try {
    const ids = getMyRequestIds().filter((x) => x !== id);
    localStorage.setItem(KEY, JSON.stringify([id, ...ids]));
  } catch {
    /* storage unavailable: the request still exists on the server */
  }
}

// Forget rides that no longer exist (e.g. after the database was reset), so the app stops asking for them.
export function forgetRequests(ids) {
  try {
    const gone = new Set(ids);
    localStorage.setItem(KEY, JSON.stringify(getMyRequestIds().filter((x) => !gone.has(x))));
  } catch {
    /* storage unavailable: nothing to forget */
  }
}
