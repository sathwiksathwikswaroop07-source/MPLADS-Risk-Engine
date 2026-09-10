import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth, PORTAL, ACTOR_ROLES } from "./auth";
import Login from "./Login";
import Worklist from "./officer/Worklist";
import Dashboard from "./officer/Dashboard";
import AlertDetail from "./officer/AlertDetail";
import Works from "./citizen/Works";
import WorkDetail from "./citizen/WorkDetail";

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

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      {/* Officers act. */}
      <Route path="/officer" element={
        <RequireRole allow={ACTOR_ROLES}>
          <Dashboard basePath="/officer" portalName="Officer workspace" />
        </RequireRole>
      } />
      <Route path="/officer/alerts" element={
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
          <Dashboard basePath="/oversight" portalName="Oversight workspace" />
        </RequireRole>
      } />
      <Route path="/oversight/alerts" element={
        <RequireRole allow={["mp", "ministry"]}>
          <Worklist basePath="/oversight" portalName="Oversight" />
        </RequireRole>
      } />
      <Route path="/oversight/alerts/:alertId" element={
        <RequireRole allow={["mp", "ministry"]}>
          <AlertDetail basePath="/oversight" portalName="Oversight" />
        </RequireRole>
      } />

      {/* Citizens see facts -- cost, dates, status, contractor, photographs
          -- and never a score. The citizen router has no code path that
          selects one, so that is structural rather than a filter here. */}
      <Route path="/citizen" element={
        <RequireRole allow={["citizen"]}><Works /></RequireRole>
      } />
      <Route path="/citizen/works/:workId" element={
        <RequireRole allow={["citizen"]}><WorkDetail /></RequireRole>
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
