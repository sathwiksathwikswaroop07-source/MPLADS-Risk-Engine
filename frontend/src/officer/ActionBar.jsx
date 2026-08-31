import { useState } from "react";
import * as api from "../api";

const VERDICTS = [
  ["substantiated", "Substantiated", "The concern was real."],
  ["not_substantiated", "Not substantiated", "Checked; the figures are explained."],
  ["could_not_verify", "Could not verify", "Verification was not possible."],
];

const MIN_NOTE = 10;

export default function ActionBar({ alert, onDone }) {
  const [dialog, setDialog] = useState(null);
  const [verdict, setVerdict] = useState("substantiated");
  const [note, setNote] = useState("");
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const id = alert.alert_id;
  const resolved = alert.status === "resolved";

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDialog(null);
      setNote("");
      // The snooze response reports a hardcoded "open" and no response
      // carries the full record, so the alert is re-fetched rather than
      // patched from what came back. This only schedules the re-read; the
      // parent unmounts or repaints this bar when it lands.
      onDone();
    } catch (err) {
      setError(err.detail || "The action could not be completed.");
      setBusy(false);
    }
  }

  return (
    <section className="action-bar">
      <div className="action-buttons">
        <button disabled={busy || resolved || alert.status === "acknowledged"}
                onClick={() => run(() => api.acknowledgeAlert(id))}>
          Acknowledge
        </button>
        <button disabled={busy || resolved}
                onClick={() => run(() => api.escalateAlert(id))}>
          Escalate
        </button>
        <button disabled={busy || resolved} onClick={() => setDialog("snooze")}>
          Snooze
        </button>
        <button className="primary" disabled={busy || resolved}
                onClick={() => setDialog("resolve")}>
          Resolve
        </button>
      </div>

      {resolved && (
        <p className="action-note">
          Closed as <strong>{alert.verdict?.replace(/_/g, " ")}</strong>
          {alert.resolution_note ? `: ${alert.resolution_note}` : ""}
        </p>
      )}

      {error && <div className="login-error">{error}</div>}

      {dialog === "resolve" && (
        <div className="dialog">
          <h3>Record what was found</h3>
          {/* Both fields are required by the API. An officer must not be able
              to clear a large alert with a bare "visited". */}
          <div className="verdict-options">
            {VERDICTS.map(([value, label, hint]) => (
              <label key={value} className={verdict === value ? "chosen" : ""}>
                <input type="radio" name="verdict" value={value}
                       checked={verdict === value}
                       onChange={() => setVerdict(value)} />
                <span><strong>{label}</strong><em>{hint}</em></span>
              </label>
            ))}
          </div>
          <textarea rows={3} value={note} placeholder="What did the verification find?"
                    onChange={(e) => setNote(e.target.value)} />
          <p className="char-hint">
            {note.trim().length < MIN_NOTE
              ? `${MIN_NOTE - note.trim().length} more characters needed.`
              : "Ready to submit."}
          </p>
          <div className="dialog-actions">
            <button onClick={() => setDialog(null)} disabled={busy}>Cancel</button>
            <button className="primary"
                    disabled={busy || note.trim().length < MIN_NOTE}
                    onClick={() => run(() => api.resolveAlert(id, {
                      verdict, resolution_note: note.trim(),
                    }))}>
              Close alert
            </button>
          </div>
        </div>
      )}

      {dialog === "snooze" && (
        <div className="dialog">
          <h3>Defer this alert</h3>
          {/* Snooze is the honest alternative to a dismiss button: the alert
              comes back rather than disappearing. */}
          <p className="dialog-note">It returns after the period; it is not cleared.</p>
          <label className="inline-field">
            Days
            <input type="number" min={1} max={180} value={days}
                   onChange={(e) => setDays(Number(e.target.value))} />
          </label>
          <div className="dialog-actions">
            <button onClick={() => setDialog(null)} disabled={busy}>Cancel</button>
            <button className="primary"
                    disabled={busy || days < 1 || days > 180}
                    onClick={() => run(() => api.snoozeAlert(id, { days }))}>
              Snooze
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
