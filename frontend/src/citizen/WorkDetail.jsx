import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api";
import Layout from "../components/Layout";
import { Loading, ErrorBox } from "../components/States";
import { rupees, isoDate, titleCase, percent } from "../format";
import { OverdueBadge, StatusPill } from "./WorkCard";
import ComplaintForm from "./ComplaintForm";
import RatingWidget from "./RatingWidget";

function Field({ label, children }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="field-value">{children}</span>
    </div>
  );
}

export default function WorkDetail() {
  const { workId } = useParams();
  const [work, setWork] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;

    setLoading(true);
    setError(null);

    api.getCitizenWork(workId)
      .then((result) => { if (current) { setWork(result); setError(null); } })
      .catch((err) => { if (current) { setError(err); setWork(null); } })
      .finally(() => { if (current) setLoading(false); });

    return () => { current = false; };
  }, [workId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const cost = work && (work.final_cost ?? work.estimated_cost);

  return (
    <Layout portalName="Citizen portal" home="/citizen">
      <Link to="/citizen" className="back-link">&larr; All works</Link>

      {loading && <Loading label="Loading work..." />}
      {!loading && error && <ErrorBox error={error} onRetry={reload} />}

      {!loading && !error && work && (
        <>
          <div className="detail-head">
            <div>
              <span className="work-type">{titleCase(work.work_type)}</span>
              <h1>{work.description}</h1>
              <p className="detail-meta">
                {work.district_name} &middot; {work.quantity} {work.unit}
              </p>
            </div>
            <div className="detail-head-side">
              <StatusPill status={work.status} />
              <OverdueBadge days={work.overdue_days} />
            </div>
          </div>

          <section className="panel">
            <h2>Cost and delivery</h2>
            <div className="field-grid">
              <Field label={work.final_cost ? "Final cost" : "Estimated cost"}>
                {rupees(cost)}
              </Field>
              <Field label="Quantity">{work.quantity} {work.unit}</Field>
              <Field label="Terrain">{titleCase(work.terrain)}</Field>
              <Field label="Area">{titleCase(work.area_type)}</Field>
              <Field label="Progress">{percent(work.progress_pct)}</Field>
              <Field label="Contractor">{work.vendor_name ?? "Not yet awarded"}</Field>
            </div>
          </section>

          <section className="panel">
            <h2>Dates</h2>
            <div className="field-grid">
              <Field label="Recommended">{isoDate(work.recommended_on)}</Field>
              <Field label="Sanctioned">{isoDate(work.sanctioned_on)}</Field>
              <Field label="Expected completion">
                {isoDate(work.expected_completion_on)}
              </Field>
              <Field label="Completed">{isoDate(work.completed_on)}</Field>
            </div>
            {work.overdue_days > 0 && (
              <p className="panel-note">
                Expected by {isoDate(work.expected_completion_on)} and still
                {" "}{titleCase(work.status).toLowerCase()} &mdash;{" "}
                {work.overdue_days} days past that date. This is arithmetic on
                the two dates above, not an assessment of the work.
              </p>
            )}
          </section>

          <section className="panel">
            <h2>Photographs</h2>
            {work.photos.length === 0 ? (
              <p className="panel-empty">
                No photographs have been uploaded for this work.
              </p>
            ) : (
              <ul className="photo-list">
                {work.photos.map((photo) => (
                  <li key={photo.evidence_id}>
                    <span className="photo-stage">{titleCase(photo.stage)}</span>
                    <span className="mono">{photo.file_path}</span>
                    <span className="photo-date">{isoDate(photo.captured_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(work.lat || work.lon) && (
            <section className="panel">
              <h2>Location</h2>
              <p className="field-value mono">
                {work.lat?.toFixed(5)}, {work.lon?.toFixed(5)}
              </p>
              <a
                className="map-link"
                href={`https://www.openstreetmap.org/?mlat=${work.lat}&mlon=${work.lon}#map=16/${work.lat}/${work.lon}`}
                target="_blank"
                rel="noreferrer"
              >
                Open in map
              </a>
            </section>
          )}

          {/* Rating a work that is still being built measures nothing, so
              the widget only appears once it is complete. */}
          {work.status === "completed" && (
            <RatingWidget
              workId={work.work_id}
              summary={work.rating_summary}
              onRated={reload}
            />
          )}

          <ComplaintForm
            workId={work.work_id}
            verifiedCount={work.complaint_count}
            onFiled={reload}
          />
        </>
      )}
    </Layout>
  );
}
