// Typed fetch wrapper for the Woolly backend.

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface PatternSummary {
  id: number;
  name: string;
  designer: string | null;
  permalink: string | null;
  ravelry_url: string | null;
  photo_url: string | null;
  free: boolean | null;
  similarity_score?: number;
  description?: string | null;
  /** Ravelry difficulty average on a 0-10 scale, serialized as a string (e.g. "3.2"). */
  difficulty?: string | null;
}

export interface PatternSearchResult {
  query: string;
  patterns: PatternSummary[];
  total: number | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // credentials: "include" so the httpOnly auth cookie travels with every call
  const response = await fetch(`${API_URL}${path}`, { credentials: "include", ...init });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; keep the default message.
    }
    throw new ApiError(response.status, detail);
  }

  return response.status === 204 ? (undefined as T) : response.json();
}

export interface SearchFilters {
  craft?: string;
  difficulty?: "beginner" | "intermediate" | "advanced";
  free?: boolean;
  category?: string;
}

export function searchPatterns(
  query: string,
  filters: SearchFilters = {}
): Promise<PatternSearchResult> {
  const params = new URLSearchParams({ q: query });
  if (filters.craft) params.set("craft", filters.craft);
  if (filters.difficulty) params.set("difficulty", filters.difficulty);
  if (filters.free !== undefined) params.set("free", String(filters.free));
  if (filters.category) params.set("category", filters.category);
  return request(`/patterns/semantic-search?${params.toString()}`);
}

export function fetchFilterOptions(): Promise<{ crafts: string[]; categories: string[] }> {
  return request("/patterns/filters");
}

// ---------- Auth ----------

export interface User {
  id: number;
  email: string;
}

function authBody(email: string, password: string): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  };
}

export function register(email: string, password: string): Promise<User> {
  return request("/auth/register", authBody(email, password));
}

export function login(email: string, password: string): Promise<User> {
  return request("/auth/login", authBody(email, password));
}

export function logout(): Promise<void> {
  return request("/auth/logout", { method: "POST" });
}

export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return await request<User>("/auth/me");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

// ---------- Saved patterns ----------

export interface Library {
  patterns: PatternSummary[];
  total: number;
}

export function savePattern(ravelryId: number): Promise<void> {
  return request(`/patterns/${ravelryId}/save`, { method: "POST" });
}

export function unsavePattern(ravelryId: number): Promise<void> {
  return request(`/patterns/${ravelryId}/save`, { method: "DELETE" });
}

export function fetchLibrary(): Promise<Library> {
  return request("/users/me/library");
}

// ---------- Projects ----------

export type ProjectStatus = "queue" | "active" | "hibernating" | "finished";

export interface Project {
  id: number;
  yarn: string | null;
  needle_size: string | null;
  notes: string | null;
  progress_pct: number;
  stitch_count: number;
  row_count: number;
  status: ProjectStatus;
  pattern: PatternSummary;
}

export interface ProjectCreate {
  pattern_id: number;
  yarn?: string;
  needle_size?: string;
  notes?: string;
  status?: ProjectStatus;
}

export type ProjectUpdate = Partial<
  Pick<
    Project,
    "yarn" | "needle_size" | "notes" | "status" | "progress_pct" | "stitch_count" | "row_count"
  >
>;

function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export function createProject(body: ProjectCreate): Promise<Project> {
  return request("/projects", jsonBody("POST", body));
}

export function fetchProjects(): Promise<{ projects: Project[] }> {
  return request("/projects");
}

export function updateProject(id: number, body: ProjectUpdate): Promise<Project> {
  return request(`/projects/${id}`, jsonBody("PATCH", body));
}

export function deleteProject(id: number): Promise<void> {
  return request(`/projects/${id}`, { method: "DELETE" });
}
