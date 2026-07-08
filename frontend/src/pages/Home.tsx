import { useState } from "react";
import {
  ApiError,
  searchPatterns,
  type PatternSearchResult,
  type SearchFilters,
} from "../api/client";
import { FilterBar } from "../components/FilterBar";
import { PatternCard } from "../components/PatternCard";
import { SearchBar } from "../components/SearchBar";
import { SkeletonCard } from "../components/SkeletonCard";

const SUGGESTIONS = [
  "cozy winter sweater",
  "quick gift for beginners",
  "no seaming required",
  "colorful stranded project",
  "something for my cat",
];

export function Home() {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [result, setResult] = useState<PatternSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runSearch(term: string, activeFilters: SearchFilters = filters) {
    const trimmed = term.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    try {
      setResult(await searchPatterns(trimmed, activeFilters));
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setLoading(false);
    }
  }

  function handleSuggestion(term: string) {
    setQuery(term);
    void runSearch(term);
  }

  function handleFilters(next: SearchFilters) {
    setFilters(next);
    // Re-run the current search with the new filters, if there is one
    if (result || query.trim()) void runSearch(query || result?.query || "", next);
  }

  return (
    <>
      <header className="hero">
        <p className="hero-eyebrow">Semantic pattern search</p>
        <h1 className="hero-title">Find the pattern you're imagining</h1>
        <p className="hero-subtitle">
          Describe what you want to make in your own words — Woolly understands intent, not just
          keywords.
        </p>
        <SearchBar
          value={query}
          onChange={setQuery}
          onSubmit={() => void runSearch(query)}
          disabled={loading}
        />
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="chip" onClick={() => handleSuggestion(s)}>
              {s}
            </button>
          ))}
        </div>
        <FilterBar filters={filters} onChange={handleFilters} />
      </header>

      <section className="results">
        {loading && (
          <ul className="results-list">
            {[0, 1, 2].map((i) => (
              <li key={i}>
                <SkeletonCard />
              </li>
            ))}
          </ul>
        )}

        {!loading && error && (
          <p className="results-error" role="alert">
            {error}
          </p>
        )}

        {!loading && !error && result && (
          <>
            <p className="results-label">
              {result.patterns.length} results for “{result.query}”
            </p>
            <ul className="results-list">
              {result.patterns.map((p) => (
                <li key={p.id}>
                  <PatternCard pattern={p} />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}
