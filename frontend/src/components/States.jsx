// Loading, empty and error are required on every page, so they share one
// shape and one set of styles.

export function Loading({ label = "Loading..." }) {
  return <div className="state-box"><span className="spinner" />{label}</div>;
}

export function Empty({ title, hint }) {
  return (
    <div className="state-box empty">
      <strong>{title}</strong>
      {hint && <span className="state-hint">{hint}</span>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  // An out-of-scope alert returns 404 rather than 403, deliberately: the
  // response must not confirm that the row exists. So "not found" and "not
  // yours" are one message here, which is the intended behaviour.
  const message =
    error?.status === 404
      ? "Not found, or outside the area your account covers."
      : error?.status === 403
        ? error.detail || "Your account cannot view this."
        : error?.detail || error?.message || "Something went wrong.";

  return (
    <div className="state-box error">
      <strong>{message}</strong>
      {onRetry && error?.status !== 404 && error?.status !== 403 && (
        <button onClick={onRetry}>Try again</button>
      )}
    </div>
  );
}
