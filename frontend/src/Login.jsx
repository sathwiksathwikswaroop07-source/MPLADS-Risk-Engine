import { useCallback, useRef, useState } from "react";
import { useLocation, useNavigate, Navigate } from "react-router-dom";
import { useAuth, PORTAL, ROLE_LABEL } from "./auth";
import { ApiError } from "./api";
import emblem from "./assets/ashoka-emblem.png";
import IntroSequence from "./components/IntroSequence";
import "./login.css";

// The role dropdown is a filter, not a claim: the server matches it in the
// WHERE clause and returns the same generic error whichever part failed.
// Ordered as the roster reads, with the demo's district officer preselected.
const ROLES = ["citizen", "mp", "district_officer", "state_officer", "ministry"];

const ROLE_SCOPE = {
  citizen: "Public ledger",
  mp: "Constituency view",
  district_officer: "Implementation",
  state_officer: "Nodal review",
  ministry: "National oversight",
};

// Seeded by backend/generate_data.py, which is also where the password
// lives. Shown rather than hidden: this build is the prototype, and an
// unlabelled block of credentials nobody can test is worse than a labelled
// one.
//
// Selecting an account only fills the three fields a human would type -- it
// does not sign in. The role stays a filter the server checks in its WHERE
// clause, so picking an account and then changing the dropdown by hand still
// fails, which is worth demonstrating.
const DEMO_PASSWORD = "mplads2026";
const DEMO_ACCOUNTS = [
  { username: "do.pune", role: "district_officer", note: "Pune worklist" },
  { username: "do.nashik", role: "district_officer", note: "Nashik worklist" },
  { username: "so.mh", role: "state_officer", note: "Adds MP-level alerts" },
  { username: "ministry.mospi", role: "ministry", note: "Read-only, national" },
  { username: "citizen001", role: "citizen", note: "Facts, never a score" },
];

export default function Login() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const loginSectionRef = useRef(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("district_officer");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Fills the form and stops there, deliberately: the submit path stays the
  // single place sign-in happens, and on a projector the filled form is worth
  // seeing before it is sent.
  const fillDemoAccount = useCallback((account) => {
    setUsername(account.username);
    setPassword(DEMO_PASSWORD);
    setRole(account.role);
    setError("");
  }, []);

  const onSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      if (busy) return;
      setError("");

      if (!username.trim() || !password) {
        setError("Enter a username and password.");
        return;
      }

      setBusy(true);
      try {
        const signedIn = await signIn(username.trim(), password, role);
        // Where the guard sent them, else their portal. A citizen who deep
        // linked into /officer is not sent back there -- PORTAL wins.
        const target = PORTAL[signedIn.role] ?? "/";
        const from = location.state?.from?.pathname;
        navigate(from && from.startsWith(target) ? from : target, { replace: true });
      } catch (err) {
        // The server answers with one generic message whichever part failed;
        // repeating it here keeps the client from being more specific.
        setError(
          err instanceof ApiError
            ? err.detail || "Invalid credentials."
            : "Could not reach the server. Is the backend running?",
        );
        setBusy(false);
      }
    },
    [busy, username, password, role, signIn, navigate, location],
  );

  // Already signed in: skip the form rather than letting someone log in twice.
  if (user) return <Navigate to={PORTAL[user.role] ?? "/"} replace />;

  return (
    <div className="login-page">
      <IntroSequence onContinue={() => loginSectionRef.current?.scrollIntoView({ behavior: "smooth" })} />

      <section ref={loginSectionRef} className="login-section" id="login">
        <div className="login-wrap">
          <div className="login-intro">
            <div className="tag">Restricted access</div>
            <h1>Sign in to KAVACH</h1>
            <p>
              This console ranks MPLADS works, MPs and districts by how far their
              numbers deviate from comparable ones and from scheme rules, so an
              officer can verify them. Access is scoped to your registered role.
            </p>
            <div className="roster">
              {ROLES.map((r) => (
                <div key={r}>
                  <span>{ROLE_LABEL[r]}</span>
                  <span>{ROLE_SCOPE[r]}</span>
                </div>
              ))}
            </div>

          </div>

          <form className="login-card" onSubmit={onSubmit} autoComplete="off">
            <div className="mark">
              <img src={emblem} alt="" aria-hidden="true" />
              <div className="marktext">
                <strong>MPLADS Risk Engine</strong>
                Members of Parliament Local Area Development Scheme
              </div>
            </div>

            {error ? (
              <div className="login-error" role="alert">
                {error}
              </div>
            ) : null}

            <div className="field">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="role">Signing in as</label>
              <select
                id="role"
                name="role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </select>
            </div>

            <p className="login-note">
              The role is checked against your account. Choosing a role you do
              not hold will not sign you in.
            </p>

            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>

            {/* Directly under the button, inside the form: an evaluator should
                not have to find these in the panel beside it. */}
            <div className="demo-accounts">
              <p className="demo-caption">
                Demo accounts — password <code>{DEMO_PASSWORD}</code>. Selecting
                one fills the form above; press Sign in.
              </p>
              <div className="demo-chips">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.username}
                    type="button"
                    className="demo-chip"
                    onClick={() => fillDemoAccount(account)}
                  >
                    <span className="demo-chip-name">{account.username}</span>
                    <span className="demo-chip-note">{account.note}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="login-foot">
              <span>SIH26102</span>
              <span>v0.1 prototype</span>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
