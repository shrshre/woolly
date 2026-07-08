import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  fetchLibrary,
  type PatternSummary,
  type ProjectCreate,
  type ProjectStatus,
} from "../api/client";

interface AddProjectModalProps {
  onClose: () => void;
  onCreate: (body: ProjectCreate) => Promise<void>;
}

export function AddProjectModal({ onClose, onCreate }: AddProjectModalProps) {
  const [library, setLibrary] = useState<PatternSummary[] | null>(null);
  const [patternId, setPatternId] = useState<number | "">("");
  const [yarn, setYarn] = useState("");
  const [needle, setNeedle] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("queue");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchLibrary()
      .then((lib) => setLibrary(lib.patterns))
      .catch(() => setLibrary([]));
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (patternId === "") return;

    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        pattern_id: patternId,
        yarn: yarn || undefined,
        needle_size: needle || undefined,
        notes: notes || undefined,
        status,
      });
      onClose();
    } catch {
      setError("Could not create the project. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-label="Add project"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="modal-title">New project</h2>

        {library !== null && library.length === 0 ? (
          <p className="modal-empty">
            Projects start from a saved pattern. <Link to="/">Search</Link> and bookmark one first —
            your <Link to="/library">library</Link> is empty.
          </p>
        ) : (
          <form onSubmit={handleSubmit}>
            <label className="auth-label" htmlFor="project-pattern">
              Pattern (from your library)
            </label>
            <select
              id="project-pattern"
              className="auth-input project-input"
              value={patternId}
              onChange={(e) => setPatternId(e.target.value ? Number(e.target.value) : "")}
              required
            >
              <option value="" disabled>
                {library === null ? "Loading…" : "Choose a pattern"}
              </option>
              {(library ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.designer ? ` — ${p.designer}` : ""}
                </option>
              ))}
            </select>

            <label className="auth-label" htmlFor="project-yarn">
              Yarn
            </label>
            <input
              id="project-yarn"
              className="auth-input project-input"
              value={yarn}
              onChange={(e) => setYarn(e.target.value)}
              placeholder="e.g. Malabrigo Rios, 3 skeins"
            />

            <label className="auth-label" htmlFor="project-needle">
              Needle / hook size
            </label>
            <input
              id="project-needle"
              className="auth-input project-input"
              value={needle}
              onChange={(e) => setNeedle(e.target.value)}
              placeholder="e.g. US 8 / 5.0mm"
            />

            <label className="auth-label" htmlFor="project-notes">
              Notes
            </label>
            <textarea
              id="project-notes"
              className="auth-input project-textarea"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />

            <label className="auth-label" htmlFor="project-status">
              Status
            </label>
            <select
              id="project-status"
              className="auth-input project-input"
              value={status}
              onChange={(e) => setStatus(e.target.value as ProjectStatus)}
            >
              <option value="queue">Queue</option>
              <option value="active">Active</option>
              <option value="hibernating">Hibernating</option>
              <option value="finished">Finished</option>
            </select>

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}

            <div className="modal-actions">
              <button
                type="submit"
                className="btn-primary"
                disabled={submitting || patternId === ""}
              >
                {submitting ? "Creating…" : "Create project"}
              </button>
              <button type="button" className="btn-ghost" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
