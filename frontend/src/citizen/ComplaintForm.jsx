import { useState } from "react";
import * as api from "../api";
import PhotoCapture from "./PhotoCapture";

// ComplaintRequest enforces min_length=10 server-side. Mirrored here so the
// refusal is immediate rather than a round trip, but the server stays the
// authority -- this is a courtesy, not a validation boundary.
const MIN_TEXT = 10;
const MAX_TEXT = 2000;

// Coordinates are requested ONLY when a photograph is attached.
//
// This reverses an earlier decision not to ask at all -- the reasoning then
// was that a geolocation prompt on a civic page costs more trust than two
// coordinates are worth, and on its own that still holds. A photograph
// changes the trade: together they let an officer confirm the report came
// from the site, which is the whole reason the capture exists. Declining is
// always allowed and the report still sends.
//
// What they are not: proof. Browser coordinates are client-asserted and
// trivially spoofed. They are an input to an officer's verification, never a
// substitute for it.
function requestPosition() {
  if (!navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => resolve(null),               // declined or unavailable: carry on
      { timeout: 8000, maximumAge: 60000 },
    );
  });
}

export default function ComplaintForm({ workId, verifiedCount, onFiled }) {
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState(null);
  const [shareLocation, setShareLocation] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const position = photo && shareLocation ? await requestPosition() : null;
      const result = await api.fileComplaint(workId, {
        text: text.trim(),
        photo,
        lat: position?.lat ?? null,
        lon: position?.lon ?? null,
      });
      setDone(result.message);
      setText("");
      setPhoto(null);
      // The parent shows a verified-report count that this may change.
      onFiled?.();
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

          <div className="capture-block">
            <span className="capture-label">Photograph (optional)</span>
            <p className="panel-note">
              A photograph of the site helps the officer verifying your report.
            </p>
            <PhotoCapture photo={photo} onChange={setPhoto} disabled={submitting} />

            {photo && (
              <label className="capture-consent">
                <input
                  type="checkbox"
                  checked={shareLocation}
                  onChange={(e) => setShareLocation(e.target.checked)}
                  disabled={submitting}
                />
                <span>
                  Attach my location, so the officer can see where this was
                  taken. Your photograph is stored without any camera or device
                  details either way.
                </span>
              </label>
            )}
          </div>

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
