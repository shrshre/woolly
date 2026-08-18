import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Nav() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <nav className="nav">
      <div className="nav-top">
        <Link className="nav-logo" to="/">
          Woolly<span className="logo-dot">.</span>
        </Link>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={menuOpen}
          aria-controls="nav-menu"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="nav-toggle-bar" />
          <span className="nav-toggle-bar" />
          <span className="nav-toggle-bar" />
        </button>
      </div>
      <div id="nav-menu" className={`nav-right${menuOpen ? " nav-right--open" : ""}`}>
        <Link className="nav-link" to="/library">
          My library
        </Link>
        <Link className="nav-link" to="/projects">
          Projects
        </Link>
        <Link className="nav-link" to="/grid-maker">
          Grid maker
        </Link>
        <Link className="nav-link" to="/counter">
          Counter
        </Link>
        {user ? (
          <>
            <span className="nav-user">{user.email}</span>
            <button type="button" className="btn-primary nav-auth-btn" onClick={handleLogout}>
              Sign out
            </button>
          </>
        ) : (
          <Link className="nav-auth-link" to="/login">
            <button type="button" className="btn-primary nav-auth-btn">
              Sign in
            </button>
          </Link>
        )}
      </div>
    </nav>
  );
}
