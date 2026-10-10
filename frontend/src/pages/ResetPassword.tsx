import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function ResetPassword() {
  const { resetPassword } = useAuth();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const tokenMissing = token.length < 16;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Choose a new password</h1>
        {tokenMissing ? (
          <>
            <p className="auth-message">
              This reset link is missing or incomplete. Request a new one from the login page.
            </p>
            <p className="auth-alt">
              <Link to="/forgot-password">Forgot your password?</Link>
            </p>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <label className="auth-label" htmlFor="password">
              New password
            </label>
            <input
              id="password"
              type="password"
              className="auth-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
            <label className="auth-label" htmlFor="confirm">
              Confirm password
            </label>
            <input
              id="confirm"
              type="password"
              className="auth-input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
              {submitting ? "One moment…" : "Update password"}
            </button>
          </form>
        )}
        <p className="auth-alt">
          <Link to="/login">Back to log in</Link>
        </p>
      </div>
    </div>
  );
}
