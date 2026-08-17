// Typed fetch wrapper for the Woolly backend.

import { getSessionId } from "../utils/session";

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
  /** Cross-encoder relevance score (0-1); absent when the reranker was unavailable. */
  rerank_score?: number | null;
  relevance_label?: string | null;
}

export interface PatternSearchResult {
  query: string;
  patterns: PatternSummary[];
  total: number | null;
  /** Id of the logged search event, for attributing later save/click interactions. */
  search_event_id?: number | null;
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
  filters: SearchFilters = {},
  { offset = 0, limit = 10 }: { offset?: number; limit?: number } = {}
): Promise<PatternSearchResult> {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  if (filters.craft) params.set("craft", filters.craft);
  if (filters.difficulty) params.set("difficulty", filters.difficulty);
  if (filters.free !== undefined) params.set("free", String(filters.free));
  if (filters.category) params.set("category", filters.category);
  params.set("session_id", getSessionId());
  return request(`/patterns/semantic-search?${params.toString()}`);
}

/** Find patterns whose photos look like the uploaded image (CLIP similarity). */
export function visualSearchPatterns(file: File, limit = 10): Promise<PatternSearchResult> {
  const params = new URLSearchParams({ limit: String(limit), session_id: getSessionId() });
  const body = new FormData();
  body.append("file", file);
  return request(`/patterns/visual-search?${params.toString()}`, { method: "POST", body });
}

export type InteractionAction = "save" | "ravelry_click";

/** Log a save/click on a search result. Fire-and-forget; uses keepalive so the
 *  request survives a tab closing (e.g. a Ravelry link opening in a new tab). */
export function logInteraction(
  ravelryId: number,
  body: { search_event_id: number; position: number; action: InteractionAction }
): void {
  try {
    void fetch(`${API_URL}/patterns/${ravelryId}/interactions`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // Analytics is best-effort; never let it disrupt the UI.
  }
}

export function fetchFilterOptions(): Promise<{ crafts: string[]; categories: string[] }> {
  return request("/patterns/filters");
}

// ---------- Ask Woolly (conversational search) ----------

export interface AskTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AskResult {
  question: string;
  answer: string;
  /** The patterns the answer is grounded in, in citation order: [1] is patterns[0]. */
  patterns: PatternSummary[];
  /** How the question was actually searched, after filter extraction. */
  search_query: string;
  filters_used: SearchFilters;
  /** True when the extracted filters matched nothing and were dropped. */
  filters_relaxed: boolean;
  search_event_id?: number | null;
}

/** Whether the server has conversational search configured (needs an LLM key). */
export function fetchAskCapability(): Promise<{ available: boolean }> {
  return request("/patterns/ask/capability");
}

/** Ask a question in plain English. History is prior turns, oldest first. */
export function askPatterns(question: string, history: AskTurn[] = []): Promise<AskResult> {
  const params = new URLSearchParams({ session_id: getSessionId() });
  return request(`/patterns/ask?${params.toString()}`, jsonBody("POST", { question, history }));
}

// ---------- Recommendations ----------

export interface Recommendations {
  patterns: PatternSummary[];
  total: number;
  /** "personalized" = from your library + search history; "popular" = engagement-ranked fallback. */
  source: "personalized" | "popular";
}

export function fetchRecommendations(limit = 8): Promise<Recommendations> {
  return request(`/patterns/recommendations?limit=${limit}`);
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
