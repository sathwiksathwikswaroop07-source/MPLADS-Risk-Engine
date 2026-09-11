import { useState } from "react";
import * as api from "../api";

const STARS = [1, 2, 3, 4, 5];
const MAX_COMMENT = 500;

/**
 * A citizen's 1-5 rating of a completed work.
 *
 * Shown only for completed works: rating a road that is still being built
 * measures nothing. The average is public; who rated what is not.
 *
 * This is not a risk score and is never presented as one. It feeds no check
 * and awards no points -- an unverified public rating driving a score would
 * be an accusation the system has not earned.
 */
export default function RatingWidget({ workId, summary, onRated }) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.rateWork(workId, {
        stars,
        comment: comment.trim() || null,
      });
      setDone(result.message);
      onRated?.();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  const count = summary?.count ?? 0;

  return (
    <section className="panel">
      <h2>Rate this work</h2>

      {count > 0 ? (
        <p className="rating-summary">
          <strong>{summary.average}</strong> out of 5
          <span className="rating-count">
            {" "}from {count} {count === 1 ? "resident" : "residents"}
          </span>
        </p>
      ) : (
        <p className="panel-note">No ratings yet. Yours would be the first.</p>
      )}

      {done ? (
        <div className="complaint-done">{done}</div>
      ) : (
        <form onSubmit={submit}>
          <div className="star-row" role="radiogroup" aria-label="Rating out of five">
            {STARS.map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={stars === value}
                aria-label={`${value} out of 5`}
                className={value <= stars ? "star on" : "star"}
                onClick={() => setStars(value)}
                disabled={submitting}
              >
                ★
              </button>
            ))}
          </div>

          <textarea
            rows={2}
            value={comment}
            maxLength={MAX_COMMENT}
            placeholder="Anything you would like to add? (optional)"
            onChange={(e) => setComment(e.target.value)}
            disabled={submitting}
          />

          {/* 409 is UNIQUE(work_id, user_id) -- one rating per resident per
              work is what stops one person moving the average. Expected, so
              it reads as a statement rather than an error. */}
          {error && (
            <div className={error.status === 409 ? "complaint-note" : "login-error"}>
              {error.status === 409
                ? "You have already rated this work."
                : error.detail || "Your rating could not be sent."}
            </div>
          )}

          <div className="dialog-actions">
            <button type="submit" disabled={submitting || stars === 0}>
              {submitting ? "Sending..." : "Submit rating"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
