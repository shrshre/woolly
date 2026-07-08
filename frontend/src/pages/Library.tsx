import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, fetchLibrary, type PatternSummary } from "../api/client";
import { useSavedPatterns } from "../auth/SavedPatternsContext";
import { PatternCard } from "../components/PatternCard";
import { SkeletonCard } from "../components/SkeletonCard";

export function Library() {
  const { savedIds } = useSavedPatterns();
  const [patterns, setPatterns] = useState<PatternSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLibrary()
      .then((lib) => setPatterns(lib.patterns))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Could not load your library.")
      );
  }, []);

  // Filter by the live saved set so optimistic unsaves disappear immediately
  const visible = patterns?.filter((p) => savedIds.has(p.id)) ?? null;

  return (
    <section className="library-page">
      <h1 className="library-title">My library</h1>

      {error && (
        <p className="results-error" role="alert">
          {error}
        </p>
      )}

      {!error && visible === null && (
        <ul className="results-list">
          {[0, 1].map((i) => (
            <li key={i}>
              <SkeletonCard />
            </li>
          ))}
        </ul>
      )}

      {!error && visible !== null && visible.length === 0 && (
        <p className="library-empty">
          Nothing saved yet. <Link to="/">Search for a pattern</Link> and tap the bookmark to keep
          it here.
        </p>
      )}

      {!error && visible !== null && visible.length > 0 && (
        <>
          <p className="results-label">
            {visible.length} saved {visible.length === 1 ? "pattern" : "patterns"}
          </p>
          <ul className="results-list">
            {visible.map((p) => (
              <li key={p.id}>
                <PatternCard pattern={p} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
