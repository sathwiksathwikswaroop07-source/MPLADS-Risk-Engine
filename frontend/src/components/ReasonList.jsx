import SeverityBadge from "./SeverityBadge";

// The only component in the application that prints total_score.
//
// `reasons` is required and an empty list renders nothing, so a bare number
// cannot reach the screen: there is no other component that accepts a score
// at all. That makes "every score is shown with its reasons" a property of
// the code rather than something a reviewer has to remember.

const EVIDENCE_LABEL = {
  value: "Unit cost",
  median: "Peer median",
  ratio: "Ratio",
  peer_count: "Peers compared",
  peer_level: "Peer group",
  days_since_sanction: "Days since sanction",
  sanctioned_on: "Sanctioned",
  expected_completion_on: "Expected by",
  progress_pct: "Progress",
  status: "Status",
  other_work_id: "Matching work",
  other_description: "Matching description",
  gap_days: "Sanctioned apart",
  cost_spread: "Cost spread",
  match_count: "Matches",
  payment_ratio: "Paid",
  progress_ratio: "Work done",
  gap: "Gap",
  paid: "Amount paid",
  cost: "Sanctioned cost",
  evidence_rows: "Evidence rows",
  stale_days: "Days since update",
  shared_photo_work_ids: "Shared photos with",
  verified_complaints: "Verified reports",
};

// Keys that exist for the scorer's benefit rather than the officer's.
const HIDDEN = new Set(["raw_points", "components"]);

function formatValue(value) {
  if (value === null || value === undefined) return "--";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString("en-IN") : value.toFixed(2);
  }
  return String(value).replace(/_/g, " ");
}

// The evidence bag is deliberately heterogeneous -- C1 carries median/ratio/
// peer_count, C7 carries payment_ratio/stale_days. Rendering it generically
// is what keeps this one component instead of eight.
function EvidenceBag({ evidence }) {
  if (!evidence) return null;
  const entries = Object.entries(evidence).filter(
    ([k, v]) => !HIDDEN.has(k) && v !== null && v !== undefined && v !== "",
  );
  if (!entries.length) return null;

  return (
    <dl className="evidence-bag">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{EVIDENCE_LABEL[key] ?? key.replace(/_/g, " ")}</dt>
          <dd>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function ReasonList({ score, severity, reasons, compact = false }) {
  if (!reasons?.length) return null;

  return (
    <div className="reasons">
      <SeverityBadge score={score} severity={severity} />
      <ul className={compact ? "reason-items compact" : "reason-items"}>
        {reasons.map((r) => (
          <li key={r.check}>
            <div className="reason-head">
              <span className="check-tag">{r.check}</span>
              <span className="points">+{r.points}</span>
            </div>
            <p className="reason-text">{r.reason}</p>
            {!compact && <EvidenceBag evidence={r.evidence} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
