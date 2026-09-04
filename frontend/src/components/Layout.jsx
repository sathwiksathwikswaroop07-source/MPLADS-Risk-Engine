import { NavLink, Link } from "react-router-dom";
import { useAuth, ROLE_LABEL } from "../auth";

function NavItem({ to, end, children }) {
  return <NavLink to={to} end={end} className={({ isActive }) => `side-link${isActive ? " active" : ""}`}>{children}</NavLink>;
}

export default function Layout({ children, portalName, home }) {
  const { user, signOut } = useAuth();
  const isCitizen = user?.role === "citizen";
  const isOfficer = user && ["district_officer", "state_officer"].includes(user.role);
  const isOversight = user && ["mp", "ministry"].includes(user.role);
  const alertsPath = isOversight ? "/oversight/alerts" : "/officer/alerts";

  return (
    <div className="shell">
      <header className="topbar">
        <Link to={home} className="brand">
          <span className="brand-mark">MPLADS</span>
          <span className="brand-sub">{portalName}</span>
        </Link>
        {user && (
          <div className="user-chip">
            <span className="user-name">{user.full_name || user.username}</span>
            <span className="user-role">{ROLE_LABEL[user.role] ?? user.role}</span>
            <button onClick={signOut}>Sign out</button>
          </div>
        )}
      </header>
      <div className="app-body">
        {user && !isCitizen && (
          <aside className="sidebar">
            <div className="sidebar-label">Workspace</div>
            {isOfficer && <NavItem to="/officer" end>Overview</NavItem>}
            {isOversight && <NavItem to="/oversight" end>Overview</NavItem>}
            {(isOfficer || isOversight) && <NavItem to={alertsPath}>Alerts</NavItem>}
            <div className="sidebar-note">
              <strong>Human verification</strong>
              <span>Scores raise questions; officers make the final decision.</span>
            </div>
          </aside>
        )}
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
