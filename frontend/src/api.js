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

  // FormData must NOT get an explicit Content-Type: the browser has to set it
  // itself so it can append the multipart boundary, and JSON.stringify would
  // turn the whole upload into "[object FormData]".
  const isForm = body instanceof FormData;

  const res = await fetch(BASE + path, {
    method,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
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

// --- citizen ---------------------------------------------------------------
//
// This router has no access to a risk score, so none of these can return one.
// The guarantee is the absence of the field server-side, not a filter here.

// No district or constituency parameter exists to pass: the scope comes from
// the token. A citizen cannot widen it by editing a URL.
export function getCitizenWorks({ status, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return request(`/citizen/works?${params}`);
}

export function getCitizenWork(workId) {
  return request(`/citizen/works/${workId}`);
}

// UNIQUE(work_id, user_id) means a second attempt returns 409 rather than
// quietly succeeding -- that constraint is what keeps C6's distinct-reporter
// count meaningful, so the UI reports the refusal instead of hiding it.
// Multipart, because a report may carry a photograph captured at the site.
// Every field is optional except the text, and a report with no photograph
// and no coordinates behaves exactly as it always has.
export function fileComplaint(workId, { text, lat = null, lon = null, photo = null }) {
  const form = new FormData();
  form.append("text", text);
  if (lat != null) form.append("lat", String(lat));
  if (lon != null) form.append("lon", String(lon));
  if (photo) form.append("photo", photo, "capture.jpg");

  return request(`/citizen/works/${workId}/complaint`, {
    method: "POST",
    body: form,
  });
}

// The photograph is fetched by complaint id through a scoped route, never by
// a path -- the storage layout never reaches the browser, and a citizen from
// another constituency gets a 404 rather than the image.
//
// Fetched as a blob rather than handed to <img src>, because the route needs
// the Authorization header and an <img> cannot send one. The caller owns the
// returned object URL and must revokeObjectURL it on unmount.
export async function complaintPhotoObjectUrl(complaintId, portal = "citizen") {
  const token = storedToken();
  const res = await fetch(`${BASE}/${portal}/complaints/${complaintId}/photo`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401) clearSession();
    // 404 is the ordinary case in deployment, not an anomaly: Render's free
    // tier has no persistent disk, so uploads do not survive a restart.
    throw new ApiError(res.status, "Photograph unavailable.");
  }
  return URL.createObjectURL(await res.blob());
}

// UNIQUE(work_id, user_id) again: one rating per citizen per work, so a
// second attempt is refused rather than quietly replacing the first.
export function rateWork(workId, { stars, comment = null }) {
  return request(`/citizen/works/${workId}/rating`, {
    method: "POST",
    body: { stars, comment },
  });
}

// Verifying is what makes a public report count towards C6, so it is
// restricted to the two officer roles and written to the audit log.
export function verifyComplaint(complaintId) {
  return request(`/officer/complaints/${complaintId}/verify`, {
    method: "POST",
  });
}
