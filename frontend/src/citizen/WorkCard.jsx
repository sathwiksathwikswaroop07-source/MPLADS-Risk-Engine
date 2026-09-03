import { Link } from "react-router-dom";
import { rupees, isoDate, titleCase, percent } from "../format";

// Delay is arithmetic on two stored fields, not a score: overdue_days comes
// from the API, which subtracts expected_completion_on from the reference
// date. The frontend never recomputes it.
export function OverdueBadge({ days }) {
  if (!days) return null;
  return <span className="overdue-badge">{days} days overdue</span>;
}

export function StatusPill({ status }) {
  return (
    <span className={`work-status status-${status}`}>{titleCase(status)}</span>
  );
}

export default function WorkCard({ work }) {
  // COALESCE(final_cost, estimated_cost) is the cost convention everywhere in
  // this project. final_cost alone is NULL until a work completes.
  const cost = work.final_cost ?? work.estimated_cost;

  return (
    <Link to={`/citizen/works/${work.work_id}`} className="work-card">
      <div className="work-card-head">
        <span className="work-type">{titleCase(work.work_type)}</span>
        <StatusPill status={work.status} />
      </div>

      <p className="work-card-desc">{work.description}</p>

      <div className="work-card-facts">
        <span>{rupees(cost)}</span>
        <span>{work.quantity} {work.unit}</span>
        <span>{work.district_name}</span>
      </div>

      <div className="work-card-foot">
        <span className="work-card-date">
          {work.completed_on
            ? `Completed ${isoDate(work.completed_on)}`
            : work.expected_completion_on
              ? `Expected by ${isoDate(work.expected_completion_on)}`
              : `Recommended ${isoDate(work.recommended_on)}`}
        </span>
        {work.status !== "completed" && (
          <span className="work-card-progress">{percent(work.progress_pct)}</span>
        )}
      </div>

      <OverdueBadge days={work.overdue_days} />
    </Link>
  );
}
