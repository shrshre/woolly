import { useRef, useState } from "react";
import {
  ApiError,
  searchPatterns,
  visualSearchPatterns,
  type PatternSummary,
  type SearchFilters,
} from "../api/client";
import { FilterBar } from "../components/FilterBar";
import { PatternCard } from "../components/PatternCard";
import { RecommendedPatterns } from "../components/RecommendedPatterns";
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
  const [searchEventId, setSearchEventId] = useState<number | null>(null);
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  // "visual" after a photo upload: results are CLIP image matches, no pagination.
  const [mode, setMode] = useState<"text" | "visual">("text");
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function runSearch(term: string, activeFilters: SearchFilters = filters) {
    const trimmed = term.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setMode("text");
    setUploadPreview(null);
    try {
      const res = await searchPatterns(trimmed, activeFilters, { offset: 0, limit: PAGE_SIZE });
      setPatterns(res.patterns);
      setTotal(res.total ?? res.patterns.length);
      setSearchEventId(res.search_event_id ?? null);
      setActiveQuery(res.query);
      setPage(1);
    } catch (err) {
      setPatterns([]);
      setTotal(0);
      setSearchEventId(null);
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
      setSearchEventId(res.search_event_id ?? null);
      setPage(next);
      resultsRef.current?.scrollIntoView({ block: "start" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setPaging(false);
    }
  }

  async function runVisualSearch(file: File) {
    if (loading) return;
    setLoading(true);
    setError(null);
    setMode("visual");
    setUploadPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
    try {
      const res = await visualSearchPatterns(file, 10);
      setPatterns(res.patterns);
      setTotal(res.total ?? res.patterns.length);
      setSearchEventId(res.search_event_id ?? null);
      setActiveQuery(res.query); // "[image search]" — display uses mode, not this
      setPage(1);
    } catch (err) {
      setPatterns([]);
      setTotal(0);
      setSearchEventId(null);
      setActiveQuery(null);
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setLoading(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Reset so picking the same file again re-triggers change.
    e.target.value = "";
    if (file) void runVisualSearch(file);
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

  // Actionable suggestions for a zero-result search, derived from the query and
  // active filters — not a hardcoded message. Each becomes a clickable chip.
  function emptyStateSuggestions(): { label: string; run: () => void }[] {
    const suggestions: { label: string; run: () => void }[] = [];
    const term = activeQuery ?? query;
    const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== "");

    if (hasFilters) {
      suggestions.push({
        label: "Try removing your filters",
        run: () => {
          setFilters({});
          void runSearch(term, {});
        },
      });
    }

    const words = term.trim().split(/\s+/).filter(Boolean);
    if (words.length >= 3) {
      const broader = words.slice(-2).join(" ");
      suggestions.push({
        label: `Search “${broader}”`,
        run: () => {
          setQuery(broader);
          void runSearch(broader);
        },
      });
    } else if (words.length === 2) {
      // Two words: offer each on its own as a broader search.
      for (const w of words) {
        suggestions.push({
          label: `Search “${w}”`,
          run: () => {
            setQuery(w);
            void runSearch(w);
          },
        });
      }
    }

    return suggestions;
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
          <button
            type="button"
            className="chip chip-photo"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
          >
            <i className="ti ti-camera" aria-hidden="true"></i> Search by photo
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            hidden
          />
        </div>
        <FilterBar filters={filters} onChange={handleFilters} />
      </header>

      {!loading && !error && !activeQuery && <RecommendedPatterns />}

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

        {!loading && !error && activeQuery && total === 0 && (
          <div className="results-empty">
            <p className="results-label">No patterns found for “{activeQuery}”</p>
            {(() => {
              const suggestions = emptyStateSuggestions();
              if (suggestions.length === 0) {
                return (
                  <p className="results-empty-hint">
                    Try describing your project a little differently, or check your spelling.
                  </p>
                );
              }
              return (
                <>
                  <p className="results-empty-hint">Try a broader search:</p>
                  <div className="chips">
                    {suggestions.map((s) => (
                      <button key={s.label} type="button" className="chip" onClick={s.run}>
                        {s.label}
                      </button>
                    ))}
                  </div>
                </>
              );
            })()}
          </div>
        )}

        {!loading && !error && activeQuery && total > 0 && (
          <>
            {mode === "visual" ? (
              <div className="results-label results-label-visual">
                {uploadPreview && <img src={uploadPreview} alt="Your uploaded photo" className="upload-preview" />}
                <span>
                  {total} {total === 1 ? "pattern" : "patterns"} similar to your photo
                </span>
              </div>
            ) : (
              <p className="results-label">
                {total} {total === 1 ? "result" : "results"} for “{activeQuery}”
                {total < 10 &&
                  Object.values(filters).some((v) => v !== undefined && v !== "") && (
                    <span className="results-filter-hint">
                      {" "}
                      — only {total} {total === 1 ? "pattern matches" : "patterns match"} these
                      filters
                    </span>
                  )}
              </p>
            )}
            <ul className={paging ? "results-list is-paging" : "results-list"}>
              {patterns.map((p, i) => (
                <li key={p.id}>
                  <PatternCard
                    pattern={p}
                    searchEventId={searchEventId}
                    position={(page - 1) * PAGE_SIZE + i + 1}
                  />
                </li>
              ))}
            </ul>
            {mode === "text" && totalPages > 1 && (
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
