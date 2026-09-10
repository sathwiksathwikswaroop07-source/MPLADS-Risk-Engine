import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import Layout from "../components/Layout";
import { Loading, Empty, ErrorBox } from "../components/States";
import AlertRow from "./AlertRow";
import PriorityBanner from "./PriorityBanner";

// Fixed option lists. The API does not validate these: an unknown status or
// severity returns an empty list that looks like "no data", and an unknown
// subject_type raises a KeyError server-side. Dropdowns make both impossible.
const SEVERITIES = [
  ["", "All severities"],
  ["critical", "Critical"],
  ["high", "High"],
  ["medium", "Medium"],
];

const STATUSES = [
  ["", "All statuses"],
  ["open", "Open"],
  ["acknowledged", "Acknowledged"],
  ["escalated", "Escalated"],
  ["resolved", "Resolved"],
];

const SUBJECTS = [
  ["", "All subjects"],
  ["work", "Works"],
  ["mp", "MP compliance"],
  ["district", "District utilisation"],
  ["vendor", "Vendor conduct"],
];

export default function Worklist({ basePath, portalName }) {
  const [filters, setFilters] = useState({
    status: "", severity: "", subject_type: "",
  });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  // Bumped to re-run the fetch after an explicit retry, since the filters
  // themselves have not changed in that case.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Changing filters quickly leaves earlier requests in flight. Without
    // this guard a slow first response can land after a faster second one
    // and repaint the list with the wrong filter's rows.
    let current = true;

    setLoading(true);
    setError(null);

    api.getAlerts(filters)
      .then((result) => { if (current) { setData(result); setError(null); } })
      .catch((err) => { if (current) { setError(err); setData(null); } })
      .finally(() => { if (current) setLoading(false); });

    return () => { current = false; };
  }, [filters, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const filtered = Boolean(filters.status || filters.severity || filters.subject_type);

  function set(key, value) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <Layout portalName={portalName} home={basePath}>
      <div className="page-head">
        <h1>Alerts needing verification</h1>
        {data && (
          <span className="count">
            {data.total} {data.total === 1 ? "subject" : "subjects"} in your area
          </span>
        )}
      </div>

      {/* The list is already ordered worst-first by the server; it is never
          re-sorted here. */}
      <div className="filters">
        {[["severity", SEVERITIES], ["status", STATUSES], ["subject_type", SUBJECTS]]
          .map(([key, options]) => (
            <select key={key} value={filters[key]} onChange={(e) => set(key, e.target.value)}>
              {options.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          ))}
        {filtered && (
          <button onClick={() => setFilters({ status: "", severity: "", subject_type: "" })}>
            Clear filters
          </button>
        )}
      </div>

      {loading && <Loading label="Loading worklist..." />}
      {!loading && error && <ErrorBox error={error} onRetry={reload} />}

      {!loading && !error && data && (
        data.alerts.length === 0 ? (
          // A clear worklist and a filter that matched nothing are different
          // outcomes and must not read as the same message.
          filtered
            ? <Empty title="No alerts match these filters."
                     hint="Clear the filters to see the full worklist." />
            : <Empty title="No alerts in your area."
                     hint="Every subject you cover scored below the alert threshold." />
        ) : (
          <>
            {!filtered && <PriorityBanner alert={data.alerts[0]} basePath={basePath} />}
            <div className="alert-list">
              {data.alerts.map((a) => (
                <AlertRow key={a.alert_id} alert={a} basePath={basePath} />
              ))}
            </div>
          </>
        )
      )}
    </Layout>
  );
}
