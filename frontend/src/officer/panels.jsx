import { useEffect, useState } from "react";
import * as api from "../api";
import { rupees, isoDate, titleCase, percent } from "../format";

export function Field({ label, children }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="field-value">{children}</span>
    </div>
  );
}

function Panel({ title, note, children }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {note && <p className="panel-note">{note}</p>}
      {children}
    </section>
  );
}

// The seven per-check point columns. They exist so the number is queryable,
// and here so an officer can see which check drove the score.
const POINT_COLUMNS = [
  ["cost_points", "Cost"],
  ["delay_points", "Delay"],
  ["compliance_points", "Compliance"],
  ["duplicate_points", "Duplicate"],
  ["public_points", "Citizen reports"],
  ["evidence_points", "Evidence / payment"],
  ["utilisation_points", "Utilisation"],
];

export function PointsBreakdown({ alert }) {
  const rows = POINT_COLUMNS
    .map(([key, label]) => [label, alert[key] ?? 0])
    .filter(([, points]) => points > 0);

  if (!rows.length) return null;
  const max = Math.max(...rows.map(([, p]) => p));

  return (
    <Panel title="Where the score came from">
      <div className="breakdown">
        {rows.map(([label, points]) => (
          <div className="breakdown-row" key={label}>
            <span className="breakdown-label">{label}</span>
            <span className="breakdown-bar">
              <span style={{ width: `${(points / max) * 100}%` }} />
            </span>
            <span className="breakdown-points">{points}</span>
          </div>
        ))}
        <div className="breakdown-total">
          <span>Total</span><span>{alert.total_score}</span>
        </div>
      </div>
    </Panel>
  );
}

// Graceful degradation made visible: a check that could not run says so
// rather than silently scoring zero.
export function ChecksCoverage({ run = [], skipped = [] }) {
  const total = run.length + skipped.length;
  return (
    <Panel title="Check coverage">
      <p className="coverage-line">
        <strong>{run.length} of {total} checks ran.</strong>{" "}
        {skipped.length > 0
          ? "The rest lacked the fields they need on this subject."
          : "Every check had the data it needed."}
      </p>
      <div className="chip-row">
        {run.map((c) => <span key={c} className="chip chip-ok">{c}</span>)}
        {skipped.map((c) => <span key={c} className="chip chip-skip">{c} skipped</span>)}
      </div>
    </Panel>
  );
}

export function WorkSubject({ work }) {
  return (
    <Panel title="The work">
      <p className="work-description">{work.description}</p>
      <div className="field-grid">
        <Field label="Type">{titleCase(work.work_type)}</Field>
        <Field label="Quantity">{work.quantity} {work.unit}</Field>
        <Field label="Estimated cost">{rupees(work.estimated_cost)}</Field>
        <Field label="Final cost">{work.final_cost ? rupees(work.final_cost) : "Not yet final"}</Field>
        <Field label="District">{work.district_name}</Field>
        <Field label="Terrain">{titleCase(work.terrain)}</Field>
        <Field label="Area">{titleCase(work.area_type)}</Field>
        <Field label="Financial year">{work.fy}</Field>
        <Field label="Status">{titleCase(work.status)}</Field>
        <Field label="Progress">{percent(work.progress_pct)}</Field>
        <Field label="Recommended">{isoDate(work.recommended_on)}</Field>
        <Field label="Sanctioned">{isoDate(work.sanctioned_on)}</Field>
        <Field label="Expected by">{isoDate(work.expected_completion_on)}</Field>
        <Field label="Completed">{isoDate(work.completed_on)}</Field>
        <Field label="Last updated">{isoDate(work.last_updated_on)}</Field>
        <Field label="MP">{work.mp_name ?? "--"}</Field>
        <Field label="Agency">{work.agency_name ?? "--"}</Field>
        <Field label="Contractor">{work.vendor_name ?? "--"}</Field>
        <Field label="SC area">{work.is_sc_area ? "Yes" : "No"}</Field>
        <Field label="ST area">{work.is_st_area ? "Yes" : "No"}</Field>
      </div>
    </Panel>
  );
}

export function MpSubject({ mp }) {
  return (
    <Panel title="The Member of Parliament"
           note="Scored on scheme compliance. This is not a risk ranking of members.">
      <div className="field-grid">
        <Field label="Name">{mp.full_name}</Field>
        <Field label="House">{titleCase(mp.house)}</Field>
        <Field label="Constituency">{mp.constituency_name}</Field>
        <Field label="State">{mp.state_name}</Field>
        <Field label="Term start">{isoDate(mp.term_start)}</Field>
        <Field label="Term end">{isoDate(mp.term_end)}</Field>
      </div>
    </Panel>
  );
}

export function VendorSubject({ vendor }) {
  return (
    <Panel title="The contractor">
      <div className="field-grid">
        <Field label="Name">{vendor.name}</Field>
        <Field label="District">{vendor.district_name}</Field>
        <Field label="Registered">{isoDate(vendor.registered_on)}</Field>
      </div>
    </Panel>
  );
}

export function DistrictSubject({ district }) {
  return (
    <Panel title="The district">
      <div className="field-grid">
        <Field label="District">{district.name}</Field>
        <Field label="State">{district.state_name}</Field>
      </div>
    </Panel>
  );
}

export function PaymentsTable({ payments }) {
  return (
    <Panel title={`Payments (${payments.length})`}>
      {payments.length === 0 ? (
        <p className="panel-empty">No payment records.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Tranche</th><th>Amount</th><th>Paid on</th><th>Progress then</th><th>Voucher</th></tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr key={p.payment_id}>
                <td>{p.tranche_no}</td>
                <td>{rupees(p.amount)}</td>
                <td>{isoDate(p.paid_on)}</td>
                <td>{percent(p.progress_pct_at_payment)}</td>
                <td className="mono">{p.voucher_ref}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function ProgressTable({ updates }) {
  return (
    <Panel title={`Progress history (${updates.length})`}
           note="The history, not just the current figure. A jump from 20 to 90 in one day is visible here and nowhere else.">
      {updates.length === 0 ? (
        <p className="panel-empty">
          No progress updates recorded. Checks needing a progress history were skipped.
        </p>
      ) : (
        <table>
          <thead>
            <tr><th>Reported</th><th>Progress</th><th>By</th><th>Note</th></tr>
          </thead>
          <tbody>
            {updates.map((u) => (
              <tr key={u.update_id}>
                <td>{isoDate(u.reported_on)}</td>
                <td>{percent(u.progress_pct)}</td>
                <td>{u.reported_by ?? "--"}</td>
                <td>{u.note ?? "--"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

// Evidence is listed as records, not rendered as images: the API returns a
// file_path but the prototype serves no files, so an <img> would show a
// broken icon on every row and imply the photograph is missing when it is
// only unserved.
export function EvidenceTable({ evidence }) {
  return (
    <Panel title={`Evidence on file (${evidence.length})`}
           note="The absence of rows here is itself the signal.">
      {evidence.length === 0 ? (
        <p className="panel-empty">
          No photographs or certificates on file for this work.
        </p>
      ) : (
        <table>
          <thead>
            <tr><th>Kind</th><th>Stage</th><th>Captured</th><th>Uploaded</th><th>Geotag</th><th>File</th></tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.evidence_id}>
                <td>{titleCase(e.kind)}</td>
                <td>{titleCase(e.stage)}</td>
                <td>{isoDate(e.captured_at)}</td>
                <td>{isoDate(e.uploaded_at)}</td>
                <td>{e.exif_lat && e.exif_lon ? `${e.exif_lat}, ${e.exif_lon}` : "None"}</td>
                <td className="mono">{e.file_path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

// The photograph is behind a scoped route that needs the bearer token, so it
// is fetched as a blob rather than handed to <img src>. A missing file is the
// ordinary case in deployment -- uploads sit on an ephemeral disk -- so it
// reads as a plain line, not an error.
function ComplaintPhoto({ complaintId }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let current = true;
    api.complaintPhotoObjectUrl(complaintId, "officer")
      .then((result) => {
        objectUrl = result;
        if (current) setUrl(result);
        else URL.revokeObjectURL(result);
      })
      .catch(() => { if (current) setFailed(true); });
    return () => {
      current = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [complaintId]);

  if (failed) return <span className="mono">photograph unavailable</span>;
  if (!url) return <span className="mono">loading…</span>;
  return (
    <a href={url} target="_blank" rel="noreferrer">
      <img className="complaint-thumb" src={url}
           alt="Photograph submitted with this report" />
    </a>
  );
}

export function ComplaintsTable({ complaints, canAct, onVerified }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  async function verify(complaintId) {
    setBusy(complaintId);
    setError(null);
    try {
      await api.verifyComplaint(complaintId);
      onVerified?.();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel title={`Citizen reports (${complaints.length})`}>
      {complaints.length === 0 ? (
        <p className="panel-empty">No citizen reports on this work.</p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Filed</th><th>Verified</th><th>Report</th>
                <th>Photo</th>{canAct && <th />}
              </tr>
            </thead>
            <tbody>
              {complaints.map((c) => (
                <tr key={c.complaint_id}>
                  <td>{isoDate(c.created_at)}</td>
                  <td>{c.verified ? "Verified" : "Unverified"}</td>
                  <td>
                    {c.text}
                    {c.lat != null && c.lon != null && (
                      <div className="complaint-coords mono">
                        {c.lat.toFixed(5)}, {c.lon.toFixed(5)}
                      </div>
                    )}
                  </td>
                  <td>
                    {c.has_photo
                      ? <ComplaintPhoto complaintId={c.complaint_id} />
                      : <span className="panel-empty">None</span>}
                  </td>
                  {canAct && (
                    <td>
                      {/* Verifying is the one action here that changes a
                          score: C6 counts distinct verified reporters. */}
                      {c.verified ? null : (
                        <button type="button"
                                disabled={busy === c.complaint_id}
                                onClick={() => verify(c.complaint_id)}>
                          {busy === c.complaint_id ? "Verifying…" : "Verify"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {error && (
            <p className="login-error">
              {error.detail || "The report could not be verified."}
            </p>
          )}
          {canAct && (
            <p className="panel-note">
              Verifying a report makes it count towards this work's score at
              the next scoring run, and records who verified it.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}

export function RatingPanel({ summary }) {
  if (!summary || !summary.count) return null;
  return (
    <Panel title="Resident rating">
      <p>
        <strong>{summary.average}</strong> out of 5 from {summary.count}{" "}
        {summary.count === 1 ? "resident" : "residents"}.
      </p>
      {/* Said plainly, because a number beside a risk score invites being
          read as part of it. */}
      <p className="panel-note">
        Context for your verification. Ratings are not verified and award no
        points towards the risk score.
      </p>
    </Panel>
  );
}
