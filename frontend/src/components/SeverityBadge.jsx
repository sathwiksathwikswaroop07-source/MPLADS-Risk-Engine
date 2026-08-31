// Bands mirror config.SEVERITY_BANDS: 70 critical / 45 high / 25 medium.
// The server sends `severity` on every alert; this derivation is only the
// fallback for a score that arrives without one.
export function severityOf(score) {
  if (score >= 70) return "critical";
  if (score >= 45) return "high";
  return "medium";
}

export default function SeverityBadge({ score, severity }) {
  const band = severity ?? severityOf(score);
  return (
    <span className={`sev sev-${band}`}>
      <strong>{score}</strong>
      <span className="sev-word">{band}</span>
    </span>
  );
}
