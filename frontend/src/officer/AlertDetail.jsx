import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api";
import Layout from "../components/Layout";
import ReasonList from "../components/ReasonList";
import { Loading, ErrorBox } from "../components/States";
import ActionBar from "./ActionBar";
import { titleCase, isoDate } from "../format";
import {
  PointsBreakdown, ChecksCoverage, WorkSubject, MpSubject, VendorSubject,
  DistrictSubject, PaymentsTable, ProgressTable, EvidenceTable, ComplaintsTable,
  RatingPanel,
} from "./panels";

const ROUTE_LABEL = {
  district_officer: "District Officer",
  state_officer: "State Officer",
};

export default function AlertDetail({ basePath, portalName }) {
  const { alertId } = useParams();
  const [alert, setAlert] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Bumped after every workflow action: no action response carries the full
  // record, and snooze reports a hardcoded "open" status, so the alert is
  // always re-read rather than patched from what came back.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Guards against a response for a previous alertId landing after the
    // user has already navigated to another alert.
    let current = true;

    setLoading(true);
    setError(null);

    api.getAlert(alertId)
      .then((result) => { if (current) { setAlert(result); setError(null); } })
      .catch((err) => { if (current) { setError(err); setAlert(null); } })
      .finally(() => { if (current) setLoading(false); });

    return () => { current = false; };
  }, [alertId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return (
    <Layout portalName={portalName} home={basePath}>
      <Link className="back-link" to={basePath}>&larr; Back to worklist</Link>

      {loading && <Loading label="Loading alert..." />}
      {!loading && error && <ErrorBox error={error} onRetry={reload} />}

      {!loading && !error && alert && (
        <>
          <div className="detail-head">
            <div>
              <span className="subject-kind">{titleCase(alert.subject_type)} alert</span>
              <h1>{subjectName(alert)}</h1>
              <p className="detail-meta">
                Raised {isoDate(alert.created_at)} &middot; scored {isoDate(alert.scored_on)}
                {alert.routes_to && <> &middot; routed to the {ROUTE_LABEL[alert.routes_to] ?? alert.routes_to}</>}
              </p>
            </div>
            <span className={`status status-${alert.status}`}>{titleCase(alert.status)}</span>
          </div>

          {/* The score never appears without the sentences that produced it. */}
          <section className="panel">
            <h2>Why this was flagged</h2>
            <ReasonList
              score={alert.total_score}
              severity={alert.severity}
              reasons={alert.reasons}
            />
          </section>

          <PointsBreakdown alert={alert} />

          {alert.can_act
            ? <ActionBar alert={alert} onDone={reload} />
            : <p className="readonly-note">
                This account can review alerts but not act on them. Under the
                scheme the District Authority sanctions and verifies works.
              </p>}

          {alert.subject_type === "work" && alert.work && <WorkSubject work={alert.work} />}
          {alert.subject_type === "mp" && alert.mp && <MpSubject mp={alert.mp} />}
          {alert.subject_type === "vendor" && alert.vendor && <VendorSubject vendor={alert.vendor} />}
          {alert.subject_type === "district" && alert.district && <DistrictSubject district={alert.district} />}

          {/* These four arrive only on work subjects -- the keys are absent
              entirely for the others, so presence is what is tested. */}
          {alert.payments && <PaymentsTable payments={alert.payments} />}
          {alert.progress_updates && <ProgressTable updates={alert.progress_updates} />}
          {alert.evidence && <EvidenceTable evidence={alert.evidence} />}
          {alert.rating_summary && <RatingPanel summary={alert.rating_summary} />}
          {alert.complaints && (
            <ComplaintsTable
              complaints={alert.complaints}
              canAct={alert.can_act}
              onVerified={reload}
            />
          )}

          <ChecksCoverage run={alert.checks_run} skipped={alert.checks_skipped} />
        </>
      )}
    </Layout>
  );
}

function subjectName(alert) {
  if (alert.subject_type === "work") return alert.work?.description ?? `Work #${alert.subject_id}`;
  if (alert.subject_type === "mp") return alert.mp?.full_name ?? `MP #${alert.subject_id}`;
  if (alert.subject_type === "vendor") return alert.vendor?.name ?? `Vendor #${alert.subject_id}`;
  if (alert.subject_type === "district") return alert.district?.name ?? `District #${alert.subject_id}`;
  return `Subject #${alert.subject_id}`;
}
