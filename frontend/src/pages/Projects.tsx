import { useEffect, useState } from "react";
import {
  ApiError,
  createProject,
  deleteProject,
  fetchProjects,
  updateProject,
  type Project,
  type ProjectCreate,
  type ProjectStatus,
  type ProjectUpdate,
} from "../api/client";
import { AddProjectModal } from "../components/AddProjectModal";
import { ProjectCard } from "../components/ProjectCard";

const COLUMNS: { status: ProjectStatus; title: string }[] = [
  { status: "queue", title: "Queue" },
  { status: "active", title: "Active" },
  { status: "hibernating", title: "Hibernating" },
  { status: "finished", title: "Finished" },
];

export function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    fetchProjects()
      .then((res) => setProjects(res.projects))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Could not load projects.")
      );
  }, []);

  async function handleCreate(body: ProjectCreate) {
    const created = await createProject(body);
    setProjects((prev) => [created, ...(prev ?? [])]);
  }

  async function handleUpdate(id: number, changes: ProjectUpdate) {
    // Optimistic update; revert by refetching on failure
    setProjects((prev) => prev?.map((p) => (p.id === id ? { ...p, ...changes } : p)) ?? null);
    try {
      const updated = await updateProject(id, changes);
      setProjects((prev) => prev?.map((p) => (p.id === id ? updated : p)) ?? null);
    } catch {
      const res = await fetchProjects();
      setProjects(res.projects);
    }
  }

  async function handleDelete(id: number) {
    const before = projects;
    setProjects((prev) => prev?.filter((p) => p.id !== id) ?? null);
    try {
      await deleteProject(id);
    } catch {
      setProjects(before);
    }
  }

  return (
    <section className="projects-page">
      <div className="projects-header">
        <h1 className="library-title">Projects</h1>
        <button type="button" className="btn-primary" onClick={() => setShowModal(true)}>
          Add project
        </button>
      </div>

      {error && (
        <p className="results-error" role="alert">
          {error}
        </p>
      )}

      {!error && projects !== null && projects.length === 0 && (
        <p className="library-empty">
          No projects yet. Add one to start tracking your works-in-progress.
        </p>
      )}

      {!error && projects !== null && projects.length > 0 && (
        <div className="projects-board">
          {COLUMNS.map(({ status, title }) => {
            const column = projects.filter((p) => p.status === status);
            return (
              <div key={status} className="projects-column">
                <h2 className="column-title">
                  {title} <span className="column-count">{column.length}</span>
                </h2>
                {column.map((p) => (
                  <ProjectCard
                    key={p.id}
                    project={p}
                    onUpdate={handleUpdate}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            );
          })}
        </div>
      )}

      {showModal && (
        <AddProjectModal onClose={() => setShowModal(false)} onCreate={handleCreate} />
      )}
    </section>
  );
}
