import { useState } from "react";
import { ApiError, searchPatterns, type PatternSearchResult } from "./api/client";
import { PatternCard } from "./components/PatternCard";
import { SearchBar } from "./components/SearchBar";
import { SkeletonCard } from "./components/SkeletonCard";

const SUGGESTIONS = [
  "cozy winter sweater",
  "quick gift for beginners",
  "no seaming required",
  "colorful stranded project",
  "something for my cat",
];

export default function App() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<PatternSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runSearch(term: string) {
    const trimmed = term.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    try {
      setResult(await searchPatterns(trimmed));
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

  return (
    <>
      <nav className="nav">
        <a className="nav-logo" href="/">
          Woolly<span className="logo-dot">.</span>
        </a>
        <div className="nav-right">
          <a className="nav-link" href="#">
            My library
          </a>
          <a className="nav-link" href="#">
            Projects
          </a>
          <button type="button" className="btn-primary">
            Sign in
          </button>
        </div>
      </nav>

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

      <div className="divider"></div>
      <footer className="footer">
        Pattern data courtesy of{" "}
        <a href="https://www.ravelry.com" target="_blank" rel="noopener noreferrer">
          Ravelry
        </a>
        . All patterns link back to their designers.
      </footer>
    </>
  );
}
