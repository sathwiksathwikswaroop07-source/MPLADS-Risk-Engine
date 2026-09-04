import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import * as api from "../api";
import Layout from "../components/Layout";
import { Loading, ErrorBox, Empty } from "../components/States";
import SeverityBadge from "../components/SeverityBadge";
import { titleCase } from "../format";

const SEVERITIES = ["critical", "high", "medium"];
const STATUSES = ["open", "acknowledged", "escalated", "resolved"];

function countBy(items, key) {
  return items.reduce((out, item) => {
    const value = item?.[key];
    if (value) out[value] = (out[value] || 0) + 1;
    return out;
  }, {});
}

function BarGroup({ title, items, max }) {
  return (
    <section className="dashboard-panel">
      <div className="dashboard-panel-head">
        <h2>{title}</h2>
      </div>
      <div className="bar-list">
        {items.map(({ label, value, tone }) => (
          <div className="bar-row" key={label}>
            <div className="bar-label">
              <span>{label}</span><strong>{value}</strong>
            </div>
            <div className="bar-track" aria-hidden="true">
              <span className={tone ? `bar-fill ${tone}` : "bar-fill"} style={{ width: `${max ? Math.max((value / max) * 100, value ? 4 : 0) : 0}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Dashboard({ basePath, portalName }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    api.getAlerts({ limit: 500 })
      .then((result) => { if (current) setData(result); })
      .catch((err) => { if (current) { setError(err); setData(null); } })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const alerts = data?.alerts ?? [];
  const severityCounts = useMemo(() => countBy(alerts, "severity"), [alerts]);
  const statusCounts = useMemo(() => countBy(alerts, "status"), [alerts]);
  const scores = alerts.map((a) => Number(a.total_score)).filter(Number.isFinite);
  const avgScore = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
  const active = alerts.filter((a) => a.status !== "resolved").length;
  const highPriority = alerts.filter((a) => a.severity === "critical" || a.severity === "high").length;
  const recent = [...alerts].slice(0, 5);

  const severityItems = SEVERITIES.map((severity) => ({
    label: titleCase(severity),
    value: severityCounts[severity] || 0,
    tone: `bar-${severity}`,
  }));
  const statusItems = STATUSES.map((status) => ({
    label: titleCase(status),
    value: statusCounts[status] || 0,
  }));
  const severityMax = Math.max(...severityItems.map((x) => x.value), 1);
  const statusMax = Math.max(...statusItems.map((x) => x.value), 1);

  return (
    <Layout portalName={portalName} home={basePath}>
      <div className="page-head dashboard-head">
        <div>
          <span className="eyebrow">MPLADS Risk Engine</span>
          <h1>Risk overview</h1>
          <p className="dashboard-subtitle">A concise view of subjects that need verification in your authorised area.</p>
        </div>
        <button onClick={reload} disabled={loading}>Refresh</button>
      </div>

      {loading && <Loading label="Loading risk overview..." />}
      {!loading && error && <ErrorBox error={error} onRetry={reload} />}

      {!loading && !error && data && (
        <>
          <div className="metric-grid">
            <div className="metric-card"><span>Total flagged</span><strong>{data.total ?? alerts.length}</strong><small>Subjects in scope</small></div>
            <div className="metric-card metric-attention"><span>Needs attention</span><strong>{active}</strong><small>Not yet resolved</small></div>
            <div className="metric-card"><span>High priority</span><strong>{highPriority}</strong><small>High or critical severity</small></div>
            <div className="metric-card"><span>Average score</span><strong>{avgScore}</strong><small>Across returned alerts</small></div>
          </div>

          <div className="dashboard-grid">
            <BarGroup title="By severity" items={severityItems} max={severityMax} />
            <BarGroup title="By status" items={statusItems} max={statusMax} />
          </div>

          <section className="dashboard-panel recent-panel">
            <div className="dashboard-panel-head">
              <div>
                <h2>Priority queue</h2>
                <p>Start with the highest-scoring subjects returned by the server.</p>
              </div>
              <Link className="dashboard-link" to={`${basePath}/alerts`}>View all alerts →</Link>
            </div>

            {recent.length === 0 ? (
              <Empty title="No flagged subjects in your area." hint="The worklist is clear right now." />
            ) : (
              <div className="dashboard-alerts">
                {recent.map((alert) => (
                  <Link key={alert.alert_id} to={`${basePath}/alerts/${alert.alert_id}`} className="dashboard-alert-row">
                    <div className="dashboard-alert-main">
                      <strong>{alert.subject_label}</strong>
                      <span>{titleCase(alert.subject_type)} · {alert.reasons?.[0]?.reason || "Needs verification"}</span>
                    </div>
                    <div className="dashboard-alert-meta">
                      <SeverityBadge severity={alert.severity} score={alert.total_score} />
                      <span className={`status status-${alert.status}`}>{titleCase(alert.status)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </Layout>
  );
}
