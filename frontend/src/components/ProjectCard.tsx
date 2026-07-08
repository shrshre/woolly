import { useState } from "react";
import type { Project, ProjectStatus, ProjectUpdate } from "../api/client";

const STATUS_LABELS: Record<ProjectStatus, string> = {
  queue: "Queue",
  active: "Active",
  hibernating: "Hibernating",
  finished: "Finished",
};

const STATUSES: ProjectStatus[] = ["queue", "active", "hibernating", "finished"];

interface ProjectCardProps {
  project: Project;
  onUpdate: (id: number, changes: ProjectUpdate) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

export function ProjectCard({ project, onUpdate, onDelete }: ProjectCardProps) {
  const [editing, setEditing] = useState(false);
  const [yarn, setYarn] = useState(project.yarn ?? "");
  const [needle, setNeedle] = useState(project.needle_size ?? "");
  const [notes, setNotes] = useState(project.notes ?? "");
  const [saving, setSaving] = useState(false);

  async function saveEdits() {
    setSaving(true);
    try {
      await onUpdate(project.id, {
        yarn: yarn || null,
        needle_size: needle || null,
        notes: notes || null,
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  function cancelEdits() {
    setYarn(project.yarn ?? "");
    setNeedle(project.needle_size ?? "");
    setNotes(project.notes ?? "");
    setEditing(false);
  }

  return (
    <article className="project-card">
      <div className="project-card-head">
        <h3 className="project-name">{project.pattern.name}</h3>
        <span className={`badge status-${project.status}`}>{STATUS_LABELS[project.status]}</span>
      </div>
      {project.pattern.designer && <p className="project-designer">by {project.pattern.designer}</p>}

      <div
        className="progress-track"
        role="progressbar"
        aria-valuenow={project.progress_pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="progress-fill" style={{ width: `${project.progress_pct}%` }}></div>
      </div>
      <div className="progress-row">
        <input
          type="range"
          className="progress-slider"
          min={0}
          max={100}
          step={5}
          value={project.progress_pct}
          onChange={(e) => void onUpdate(project.id, { progress_pct: Number(e.target.value) })}
          aria-label="Progress"
        />
        <span className="progress-value">{project.progress_pct}%</span>
      </div>

      {editing ? (
        <div className="project-edit">
          <input
            className="auth-input project-input"
            value={yarn}
            onChange={(e) => setYarn(e.target.value)}
            placeholder="Yarn"
            aria-label="Yarn"
          />
          <input
            className="auth-input project-input"
            value={needle}
            onChange={(e) => setNeedle(e.target.value)}
            placeholder="Needle / hook size"
            aria-label="Needle or hook size"
          />
          <textarea
            className="auth-input project-textarea"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes"
            aria-label="Notes"
            rows={3}
          />
          <div className="project-edit-actions">
            <button type="button" className="btn-primary" onClick={saveEdits} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn-ghost" onClick={cancelEdits}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="project-details">
          {project.yarn && (
            <p className="project-detail">
              <span className="project-detail-label">Yarn</span> {project.yarn}
            </p>
          )}
          {project.needle_size && (
            <p className="project-detail">
              <span className="project-detail-label">Needles</span> {project.needle_size}
            </p>
          )}
          {project.notes && <p className="project-notes">{project.notes}</p>}
        </div>
      )}

      <div className="project-footer">
        <select
          className="project-status-select"
          value={project.status}
          onChange={(e) => void onUpdate(project.id, { status: e.target.value as ProjectStatus })}
          aria-label="Project status"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <div className="project-actions">
          {!editing && (
            <button type="button" className="icon-btn" aria-label="Edit project" onClick={() => setEditing(true)}>
              <i className="ti ti-pencil" aria-hidden="true"></i>
            </button>
          )}
          <button
            type="button"
            className="icon-btn"
            aria-label="Delete project"
            onClick={() => void onDelete(project.id)}
          >
            <i className="ti ti-trash" aria-hidden="true"></i>
          </button>
        </div>
      </div>
    </article>
  );
}
