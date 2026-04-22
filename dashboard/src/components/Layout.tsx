import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { THEMES, getTheme, setTheme } from "../utils/theme";
import { useState } from "react";
import "./styles.css";

export function Layout() {
  const { user, logout } = useAuth();
  const [theme, setThemeState] = useState(getTheme());

  const handleTheme = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setTheme(e.target.value);
    setThemeState(e.target.value);
  };

  return (
    <div className="layout">
      <header className="layout-header">
        <h1>Copilot OTel Dashboard</h1>
        <nav className="layout-nav">
          <NavLink to="/" end className={({ isActive }) => isActive ? "active" : ""}>
            Sessions
          </NavLink>
          <NavLink to="/charts" className={({ isActive }) => isActive ? "active" : ""}>
            Charts
          </NavLink>
          <NavLink to="/debug" className={({ isActive }) => isActive ? "active" : ""}>
            Debug
          </NavLink>
        </nav>
        <div className="layout-user">
          <select className="theme-select" value={theme} onChange={handleTheme}>
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          {user && <span>{user.name}</span>}
          {user && <button onClick={logout}>Sign Out</button>}
        </div>
      </header>
      <main className="layout-content">
        <Outlet />
      </main>
    </div>
  );
}
