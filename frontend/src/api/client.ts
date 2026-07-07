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

export async function searchPatterns(query: string): Promise<PatternSearchResult> {
  // Week 2: semantic search over seeded patterns (the /patterns/search Ravelry proxy still exists)
  const url = `${API_URL}/patterns/semantic-search?q=${encodeURIComponent(query)}`;
  const response = await fetch(url);

  if (!response.ok) {
    let detail = `Search failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; keep the default message.
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}
