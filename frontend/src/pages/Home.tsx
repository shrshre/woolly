import { useRef, useState } from "react";
import {
  ApiError,
  searchPatterns,
  type PatternSummary,
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

const PAGE_SIZE = 10;

export function Home() {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [patterns, setPatterns] = useState<PatternSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const resultsRef = useRef<HTMLElement>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function runSearch(term: string, activeFilters: SearchFilters = filters) {
    const trimmed = term.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    try {
      const res = await searchPatterns(trimmed, activeFilters, { offset: 0, limit: PAGE_SIZE });
      setPatterns(res.patterns);
      setTotal(res.total ?? res.patterns.length);
      setActiveQuery(res.query);
      setPage(1);
    } catch (err) {
      setPatterns([]);
      setTotal(0);
      setActiveQuery(null);
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setLoading(false);
    }
  }

  async function goToPage(next: number) {
    if (paging || !activeQuery || next === page || next < 1 || next > totalPages) return;
    setPaging(true);
    try {
      const res = await searchPatterns(activeQuery, filters, {
        offset: (next - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setPatterns(res.patterns);
      setTotal(res.total ?? total);
      setPage(next);
      resultsRef.current?.scrollIntoView({ block: "start" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setPaging(false);
    }
  }

  function handleSuggestion(term: string) {
    setQuery(term);
    void runSearch(term);
  }

  function handleFilters(next: SearchFilters) {
    setFilters(next);
    // Re-run the current search from page one with the new filters, if there is one
    if (activeQuery || query.trim()) void runSearch(query || activeQuery || "", next);
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

      <section className="results" ref={resultsRef}>
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

        {!loading && !error && activeQuery && (
          <>
            <p className="results-label">
              {total} {total === 1 ? "result" : "results"} for “{activeQuery}”
            </p>
            <ul className={paging ? "results-list is-paging" : "results-list"}>
              {patterns.map((p) => (
                <li key={p.id}>
                  <PatternCard pattern={p} />
                </li>
              ))}
            </ul>
            {totalPages > 1 && (
              <nav className="pagination" aria-label="Search result pages">
                <button
                  type="button"
                  className="page-arrow"
                  onClick={() => void goToPage(page - 1)}
                  disabled={paging || page === 1}
                  aria-label="Previous page"
                >
                  <i className="ti ti-chevron-left" aria-hidden="true"></i>
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={n === page ? "page-num active" : "page-num"}
                    onClick={() => void goToPage(n)}
                    disabled={paging}
                    aria-current={n === page ? "page" : undefined}
                  >
                    {n}
                  </button>
                ))}
                <button
                  type="button"
                  className="page-arrow"
                  onClick={() => void goToPage(page + 1)}
                  disabled={paging || page === totalPages}
                  aria-label="Next page"
                >
                  <i className="ti ti-chevron-right" aria-hidden="true"></i>
                </button>
              </nav>
            )}
          </>
        )}
      </section>
    </>
  );
}
