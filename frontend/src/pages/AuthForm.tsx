import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";

interface AuthFormProps {
  title: string;
  submitLabel: string;
  onSubmit: (email: string, password: string) => Promise<void>;
  altText: string;
  altLinkText: string;
  altLinkTo: string;
}

export function AuthForm({ title, submitLabel, onSubmit, altText, altLinkText, altLinkTo }: AuthFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(email, password);
      navigate((location.state as { from?: string } | null)?.from ?? "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">{title}</h1>
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
          <label className="auth-label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            className="auth-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            minLength={8}
            required
          />
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
            {submitting ? "One moment…" : submitLabel}
          </button>
        </form>
        <p className="auth-alt">
          {altText} <Link to={altLinkTo}>{altLinkText}</Link>
        </p>
      </div>
    </div>
  );
}
