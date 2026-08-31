import { Link } from "react-router-dom";
import { titleCase } from "../format";

// A persistent banner rather than a modal: a modal gets dismissed reflexively
// and blocks the task the officer came to do.
export default function PriorityBanner({ alert, basePath }) {
  if (!alert) return null;
  const lead = alert.reasons?.[0];

  return (
    <div className={`priority-banner sev-band-${alert.severity}`}>
      <div>
        <span className="priority-label">Highest risk in your area</span>
        <strong>{alert.subject_label}</strong>
        {lead && <p className="priority-reason">{lead.reason}</p>}
      </div>
      <Link className="priority-action" to={`${basePath}/alerts/${alert.alert_id}`}>
        Review {titleCase(alert.subject_type)} &rarr;
      </Link>
    </div>
  );
}
