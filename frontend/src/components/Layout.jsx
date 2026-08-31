import { Link } from "react-router-dom";
import { useAuth, ROLE_LABEL } from "../auth";

export default function Layout({ children, portalName, home }) {
  const { user, signOut } = useAuth();

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
      <main className="content">{children}</main>
    </div>
  );
}
