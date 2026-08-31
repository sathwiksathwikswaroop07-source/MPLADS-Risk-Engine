import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth, PORTAL, ROLE_LABEL } from "./auth";

const ROLES = ["citizen", "mp", "district_officer", "state_officer", "ministry"];

export default function Login() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("district_officer");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={PORTAL[user.role] ?? "/login"} replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const signedIn = await signIn(username.trim(), password, role);
      navigate(PORTAL[signedIn.role] ?? "/login", { replace: true });
    } catch (err) {
      // The server returns one generic message whichever part failed --
      // unknown user, wrong role, disabled account or bad password.
      setError(err.detail || "Invalid credentials.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>MPLADS Risk Engine</h1>
        <p className="login-sub">
          Anomaly detection for the Members of Parliament Local Area
          Development Scheme.
        </p>

        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <label>
          Signing in as
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </label>

        {/* The selector is an extra filter the server re-checks against the
            row, never a claim the token carries. */}
        <p className="login-note">
          The role is checked against your account. Choosing a role you do not
          hold will not sign you in.
        </p>

        {error && <div className="login-error">{error}</div>}

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
