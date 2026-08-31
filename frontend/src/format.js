// Presentation helpers only. Nothing here derives a figure the API did not
// send -- the frontend must never recompute a number that is not in the
// response.

// Money arrives as integer rupees.
export function rupees(value) {
  if (value === null || value === undefined) return "--";
  if (value >= 10000000) return `Rs ${(value / 10000000).toFixed(2)} cr`;
  if (value >= 100000) return `Rs ${(value / 100000).toFixed(2)} lakh`;
  return `Rs ${value.toLocaleString("en-IN")}`;
}

// Dates are ISO-8601 strings throughout; SQLite has no date type.
export function isoDate(value) {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
}

export function titleCase(value) {
  if (!value) return "--";
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function percent(value) {
  if (value === null || value === undefined) return "--";
  return `${Number(value).toFixed(0)}%`;
}
