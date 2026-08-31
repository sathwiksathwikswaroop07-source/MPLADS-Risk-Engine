import { createContext, useCallback, useContext, useMemo, useState } from "react";
import * as api from "./api";

// Where each role lands after login. This map is convenience, not security:
// it stops an MP deep-linking into the worklist and seeing a broken page. The
// enforcement is that every API call still returns 403 or 404.
export const PORTAL = {
  citizen: "/citizen",
  district_officer: "/officer",
  state_officer: "/officer",
  mp: "/oversight",
  ministry: "/oversight",
};

export const ROLE_LABEL = {
  citizen: "Citizen",
  mp: "Member of Parliament",
  district_officer: "District Officer",
  state_officer: "State Officer",
  ministry: "Ministry",
};

// Only district and state officers may act on an alert. The API is the
// authority (it returns can_act on every response); this mirrors it for the
// route guard alone.
export const ACTOR_ROLES = ["district_officer", "state_officer"];

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => api.storedUser());

  const signIn = useCallback(async (username, password, role) => {
    const signedIn = await api.login(username, password, role);
    setUser(signedIn);
    return signedIn;
  }, []);

  const signOut = useCallback(() => {
    api.logout();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, signIn, signOut }), [user, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
