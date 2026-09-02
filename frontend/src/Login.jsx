import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, Navigate } from "react-router-dom";
import { useAuth, PORTAL, ROLE_LABEL } from "./auth";
import { ApiError } from "./api";
import emblem from "./assets/ashoka-emblem.png";
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

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}
function smooth(t) {
  t = clamp(t, 0, 1);
  return t * t * (3 - 2 * t);
}
// Bell-shaped weight: 1 at the centre, fading to 0 by +-width. Three of these
// centred at 0.08 / 0.5 / 0.92 crossfade the scenes without any of them ever
// summing above 1 and washing the stage out.
function bell(progress, center, width) {
  return clamp(1 - smooth(Math.abs(progress - center) / width), 0, 1);
}

// Scroll-driven title sequence. Written against refs and a rAF-throttled
// scroll listener rather than getElementById so it survives remounts and
// React's StrictMode double-invoke.
function EmblemHero() {
  const trackRef = useRef(null);
  const stageRef = useRef(null);
  const emblemRef = useRef(null);
  const chakraRef = useRef(null);
  const bgRefs = [useRef(null), useRef(null), useRef(null)];
  const capRefs = [useRef(null), useRef(null), useRef(null)];
  const hintRef = useRef(null);

  useEffect(() => {
    // Honour the OS setting: the static final scene is set by CSS, and
    // driving transforms here would override it.
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motionQuery.matches) return undefined;

    let frame = 0;

    const update = () => {
      frame = 0;
      const track = trackRef.current;
      const stage = stageRef.current;
      if (!track || !stage) return;

      const max = track.clientHeight - stage.clientHeight;
      const rect = track.getBoundingClientRect();
      const p = max > 0 ? clamp(-rect.top / max, 0, 1) : 0;

      const w = [bell(p, 0.08, 0.22), bell(p, 0.5, 0.22), bell(p, 0.92, 0.22)];
      bgRefs.forEach((ref, i) => {
        if (ref.current) ref.current.style.opacity = w[i];
      });
      capRefs.forEach((ref, i) => {
        if (ref.current) ref.current.style.opacity = w[i];
      });

      if (chakraRef.current) {
        chakraRef.current.style.opacity = (w[1] * 0.9).toFixed(2);
        chakraRef.current.style.transform = `rotate(${p * 140}deg)`;
      }
      if (hintRef.current) hintRef.current.style.opacity = p < 0.05 ? 1 : 0;

      if (emblemRef.current) {
        // A flat asset cannot be turned, so it rocks in perspective instead --
        // it reads as a cast plaque catching the light.
        const rotY = Math.sin(p * Math.PI * 1.5) * 22;
        const rotX = (p - 0.5) * -10;
        const scale = 1 + Math.sin(p * Math.PI) * 0.08;
        emblemRef.current.style.transform =
          `translateY(${-p * 26}px) rotateX(${rotX}deg) rotateY(${rotY}deg) scale(${scale})`;

        const brightness = 0.85 + w[1] * 0.35 + w[2] * 0.1;
        emblemRef.current.style.filter =
          `drop-shadow(0 18px 40px var(--emblem-shadow)) brightness(${brightness})` +
          (w[2] > 0.3 ? ` drop-shadow(0 0 22px rgba(var(--vermillion-rgb), ${(w[2] * 0.45).toFixed(2)}))` : "");
      }
    };

    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
    // Refs are stable; this wires up listeners exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="login-hero">
      <div className="track" ref={trackRef}>
        <div className="stage" ref={stageRef}>
          <div className="bg-layer bg-1" ref={bgRefs[0]} />
          <div className="bg-layer bg-2" ref={bgRefs[1]} />
          <div className="bg-layer bg-3" ref={bgRefs[2]}>
            <div className="grid-overlay" />
          </div>

          <div className="chakra" ref={chakraRef} aria-hidden="true">
            <svg viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.6" />
              <g stroke="currentColor" strokeWidth="0.6" opacity="0.55">
                <line x1="50" y1="4" x2="50" y2="96" />
                <line x1="4" y1="50" x2="96" y2="50" />
                <line x1="12" y1="12" x2="88" y2="88" />
                <line x1="12" y1="88" x2="88" y2="12" />
                <line x1="27" y1="4" x2="73" y2="96" />
                <line x1="73" y1="4" x2="27" y2="96" />
                <line x1="4" y1="27" x2="96" y2="73" />
                <line x1="4" y1="73" x2="96" y2="27" />
              </g>
            </svg>
          </div>

          <div className="emblem-wrap">
            <img className="emblem" ref={emblemRef} src={emblem} alt="State Emblem of India" />
          </div>

          <div className="caption cap-1" ref={capRefs[0]}>
            <div className="eyebrow">Government of India</div>
            <div className="head">
              Members of Parliament
              <br />
              Local Area Development Scheme
            </div>
          </div>
          <div className="caption cap-2" ref={capRefs[1]}>
            <div className="eyebrow" lang="sa">सत्यमेव जयते</div>
            <div className="head">Truth Alone Triumphs</div>
            <div className="sub">₹5 crore, every MP, every year — where does it go?</div>
          </div>
          <div className="caption cap-3" ref={capRefs[2]}>
            <div className="eyebrow">SIH26102 · Prototype</div>
            <div className="head">Anomaly detection for MPLADS</div>
            <div className="sub">Sign in below ↓</div>
          </div>

          <div className="scroll-hint" ref={hintRef} aria-hidden="true">
            <span>Scroll</span>
            <span>↓</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Login() {
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("district_officer");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
      <EmblemHero />

      <section className="login-section" id="login">
        <div className="login-wrap">
          <div className="login-intro">
            <div className="tag">Restricted access</div>
            <h1>Sign in to the risk console</h1>
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
                autoFocus
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
