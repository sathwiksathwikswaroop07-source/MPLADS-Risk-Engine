// Every network call in the application lives here. No component calls fetch.

// Every API route is served under /api by the same FastAPI process that
// serves this page, so a same-origin relative base is all that is needed --
// no CORS, no build-time URL. VITE_API_BASE stays as an override for the
// split-service case (a separate static host pointing at a remote API).
// Trailing slash trimmed: the paths below all start with one, and
// "//auth/login" would 404.
const BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/+$/, "");
const TOKEN_KEY = "mplads_token";
const USER_KEY = "mplads_user";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

// --- session storage -------------------------------------------------------
// /auth/me returns only user_id, role, scope_type and scope_id -- not
// username or full_name. The login response is the only source of a display
// name, so the whole user object is persisted rather than re-fetched.

export function storedToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function storedUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// --- transport -------------------------------------------------------------

async function request(path, { method = "GET", body } = {}) {
  const token = storedToken();

  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 204) return null;

  const payload = await res.json().catch(() => null);

  if (!res.ok) {
    // A 12-hour token cannot be refreshed and there is no logout route, so an
    // expired session is only ever discovered here. Drop it and let the route
    // guard send the user to /login.
    if (res.status === 401) clearSession();
    throw new ApiError(res.status, payload?.detail ?? "Request failed.");
  }

  return payload;
}

// --- auth ------------------------------------------------------------------

// role is a filter the server re-checks against the row, never a claim. A
// citizen picking "District Officer" matches no row and login fails.
export async function login(username, password, role) {
  const data = await request("/auth/login", {
    method: "POST",
    body: { username, password, role },
  });
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  return data.user;
}

// Stateless tokens cannot be revoked; logout is a client-side discard.
export function logout() {
  clearSession();
}

export function getMe() {
  return request("/auth/me");
}

// --- officer ---------------------------------------------------------------

// Falsy filters are dropped rather than sent: the server does not validate
// these, and an unrecognised subject_type raises a KeyError -> 500.
export function getAlerts({ status, severity, subject_type, limit = 500 } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  if (subject_type) params.set("subject_type", subject_type);
  params.set("limit", String(limit));
  return request(`/officer/alerts?${params}`);
}

export function getAlert(alertId) {
  return request(`/officer/alerts/${alertId}`);
}

export function acknowledgeAlert(alertId) {
  return request(`/officer/alerts/${alertId}/acknowledge`, { method: "POST" });
}

export function escalateAlert(alertId) {
  return request(`/officer/alerts/${alertId}/escalate`, { method: "POST" });
}

export function resolveAlert(alertId, { verdict, resolution_note }) {
  return request(`/officer/alerts/${alertId}/resolve`, {
    method: "POST",
    body: { verdict, resolution_note },
  });
}

// The API accepts a note here and discards it, so the UI does not offer one.
export function snoozeAlert(alertId, { days }) {
  return request(`/officer/alerts/${alertId}/snooze`, {
    method: "POST",
    body: { days },
  });
}
