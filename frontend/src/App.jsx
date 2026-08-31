import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth, PORTAL, ACTOR_ROLES } from "./auth";
import Login from "./Login";
import Worklist from "./officer/Worklist";
import AlertDetail from "./officer/AlertDetail";
import Layout from "./components/Layout";

// Route guards keep a role off a page it would only see broken. They are not
// the access control: every API call still returns 403 or 404 on its own.
function RequireRole({ allow, children }) {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  if (!allow.includes(user.role)) {
    return <Navigate to={PORTAL[user.role] ?? "/login"} replace />;
  }
  return children;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? PORTAL[user.role] ?? "/login" : "/login"} replace />;
}

// The citizen portal is step 10. Until then a citizen login lands somewhere
// deliberate rather than on a blank screen -- and never on a score.
function CitizenStub() {
  return (
    <Layout portalName="Citizen portal" home="/citizen">
      <div className="state-box empty">
        <strong>The citizen portal is not built yet.</strong>
        <span className="state-hint">
          Works, photographs and the complaint form arrive in step 10.
        </span>
      </div>
    </Layout>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      {/* Officers act. */}
      <Route path="/officer" element={
        <RequireRole allow={ACTOR_ROLES}>
          <Worklist basePath="/officer" portalName="Officer worklist" />
        </RequireRole>
      } />
      <Route path="/officer/alerts/:alertId" element={
        <RequireRole allow={ACTOR_ROLES}>
          <AlertDetail basePath="/officer" portalName="Officer worklist" />
        </RequireRole>
      } />

      {/* Oversight watches: the same two screens, with can_act false from the
          API removing every action button. */}
      <Route path="/oversight" element={
        <RequireRole allow={["mp", "ministry"]}>
          <Worklist basePath="/oversight" portalName="Oversight" />
        </RequireRole>
      } />
      <Route path="/oversight/alerts/:alertId" element={
        <RequireRole allow={["mp", "ministry"]}>
          <AlertDetail basePath="/oversight" portalName="Oversight" />
        </RequireRole>
      } />

      <Route path="/citizen" element={
        <RequireRole allow={["citizen"]}><CitizenStub /></RequireRole>
      } />

      <Route path="/" element={<Home />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
