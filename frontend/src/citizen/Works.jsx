import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import Layout from "../components/Layout";
import { Loading, Empty, ErrorBox } from "../components/States";
import WorkCard from "./WorkCard";

// The four values works.status is constrained to. Typed as a dropdown rather
// than a free field because the API does not validate the parameter: an
// unknown status returns an empty list that reads as "no works here".
const STATUSES = [
  ["", "All works"],
  ["recommended", "Recommended"],
  ["sanctioned", "Sanctioned"],
  ["in_progress", "In progress"],
  ["completed", "Completed"],
];

const PAGE_SIZE = 24;

export default function Works() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Paging or filtering quickly leaves earlier requests in flight; without
    // this guard a slow first response can land after a faster second one and
    // repaint the list with the wrong page's rows.
    let current = true;

    setLoading(true);
    setError(null);

    api.getCitizenWorks({ status, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then((result) => { if (current) { setData(result); setError(null); } })
      .catch((err) => { if (current) { setError(err); setData(null); } })
      .finally(() => { if (current) setLoading(false); });

    return () => { current = false; };
  }, [status, page, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  return (
    <Layout portalName="Citizen portal" home="/citizen">
      <div className="page-head">
        <h1>Works in your constituency</h1>
        {data && (
          <span className="count">
            {total} {total === 1 ? "work" : "works"}
          </span>
        )}
      </div>

      <p className="portal-note">
        Public works recommended under MPLADS in your area. Cost, dates and the
        implementing contractor are public record. If something here does not
        match what you can see on the ground, open the work and report it.
      </p>

      <div className="filters">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(0); }}
        >
          {STATUSES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>

      {loading && <Loading label="Loading works..." />}
      {!loading && error && <ErrorBox error={error} onRetry={reload} />}

      {!loading && !error && data && (
        data.works.length === 0 ? (
          // A filter that matched nothing and a genuinely empty constituency
          // are different outcomes and must not read as the same message.
          status
            ? <Empty title="No works with that status."
                     hint="Choose 'All works' to see everything in your area." />
            : <Empty title="No works recorded for your constituency yet."
                     hint="Works appear here once they are entered in eSAKSHI." />
        ) : (
          <>
            <div className="work-grid">
              {data.works.map((work) => (
                <WorkCard key={work.work_id} work={work} />
              ))}
            </div>

            {total > PAGE_SIZE && (
              <div className="pager">
                <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span className="pager-position">
                  Page {page + 1} of {lastPage + 1}
                </span>
                <button disabled={page >= lastPage} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </div>
            )}
          </>
        )
      )}
    </Layout>
  );
}
