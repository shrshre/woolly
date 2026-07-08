import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Nav() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <nav className="nav">
      <Link className="nav-logo" to="/">
        Woolly<span className="logo-dot">.</span>
      </Link>
      <div className="nav-right">
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
            <button type="button" className="btn-primary" onClick={handleLogout}>
              Sign out
            </button>
          </>
        ) : (
          <Link to="/login">
            <button type="button" className="btn-primary">
              Sign in
            </button>
          </Link>
        )}
      </div>
    </nav>
  );
}
