import { Link } from "react-router-dom";
import ReasonList from "../components/ReasonList";
import { titleCase } from "../format";

// A row has no code path that renders a score on its own: the number reaches
// the screen only through ReasonList, which requires the reasons beside it.
export default function AlertRow({ alert, basePath }) {
  return (
    <Link className="alert-row" to={`${basePath}/alerts/${alert.alert_id}`}>
      <div className="alert-main">
        <div className="alert-title">
          <span className="subject-kind">{titleCase(alert.subject_type)}</span>
          <strong>{alert.subject_label}</strong>
          {alert.subject_sublabel && (
            <span className="subject-sub">{titleCase(alert.subject_sublabel)}</span>
          )}
        </div>
        <ReasonList
          score={alert.total_score}
          severity={alert.severity}
          reasons={alert.reasons}
          compact
        />
      </div>
      <div className="alert-meta">
        <span className={`status status-${alert.status}`}>
          {titleCase(alert.status)}
        </span>
        {alert.snoozed_until && (
          <span className="snoozed">Snoozed to {alert.snoozed_until}</span>
        )}
      </div>
    </Link>
  );
}
