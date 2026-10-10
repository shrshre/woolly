import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, requestPasswordReset } from "../api/client";

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Forgot your password?</h1>
        {sent ? (
          <>
            <p className="auth-message">
              If an account exists for that email, we've sent a link to reset your password. Check
              your inbox, and spam just in case.
            </p>
            <p className="auth-alt">
              <Link to="/login">Back to log in</Link>
            </p>
          </>
        ) : (
          <>
            <p className="auth-message">
              Enter the email you signed up with and we'll send a reset link.
            </p>
            <form onSubmit={handleSubmit}>
              <label className="auth-label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                className="auth-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
                {submitting ? "One moment…" : "Send reset link"}
              </button>
            </form>
            <p className="auth-alt">
              Remembered it? <Link to="/login">Log in</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
