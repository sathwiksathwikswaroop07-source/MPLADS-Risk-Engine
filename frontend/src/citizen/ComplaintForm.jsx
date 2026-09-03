import { useState } from "react";
import * as api from "../api";

// ComplaintRequest enforces min_length=10 server-side. Mirrored here so the
// refusal is immediate rather than a round trip, but the server stays the
// authority -- this is a courtesy, not a validation boundary.
const MIN_TEXT = 10;
const MAX_TEXT = 2000;

export default function ComplaintForm({ workId, verifiedCount }) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      // Location is optional and deliberately not requested from the browser:
      // a geolocation prompt on a civic page costs more trust than the two
      // coordinates are worth. The API accepts null for both.
      const result = await api.fileComplaint(workId, { text: text.trim() });
      setDone(result.message);
      setText("");
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  const tooShort = text.trim().length > 0 && text.trim().length < MIN_TEXT;

  return (
    <section className="panel">
      <h2>Report a problem</h2>

      <p className="panel-note">
        Your report goes to the District Authority for verification. Only
        reports an officer has verified count towards a work being reviewed,
        and you may file one report per work.
      </p>

      {verifiedCount > 0 && (
        <p className="complaint-count">
          {verifiedCount} verified {verifiedCount === 1 ? "report" : "reports"}
          {" "}already recorded for this work.
        </p>
      )}

      {done ? (
        <div className="complaint-done">{done}</div>
      ) : (
        <form onSubmit={submit}>
          <textarea
            rows={4}
            value={text}
            maxLength={MAX_TEXT}
            placeholder="What did you see? For example: the road is marked complete but only half of it has been surfaced."
            onChange={(e) => setText(e.target.value)}
            disabled={submitting}
          />
          <p className="char-hint">
            {tooShort
              ? `At least ${MIN_TEXT} characters.`
              : `${text.length} of ${MAX_TEXT} characters.`}
          </p>

          {/* 409 is the UNIQUE(work_id, user_id) constraint, and it is the
              expected answer to a second report rather than a fault -- so it
              reads as a plain statement, not an error. */}
          {error && (
            <div className={error.status === 409 ? "complaint-note" : "login-error"}>
              {error.status === 409
                ? "You have already reported this work."
                : error.detail || "Your report could not be sent."}
            </div>
          )}

          <div className="dialog-actions">
            <button
              type="submit"
              disabled={submitting || text.trim().length < MIN_TEXT}
            >
              {submitting ? "Sending..." : "Send report"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
