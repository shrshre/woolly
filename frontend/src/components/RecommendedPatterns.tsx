import { useEffect, useState } from "react";
import { fetchRecommendations, type Recommendations } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { PatternCard } from "./PatternCard";
import { SkeletonCard } from "./SkeletonCard";

/** Homepage recommendations, shown before the first search. Personalized from
 *  the user's library and search history when signed in with history;
 *  otherwise a popular-patterns fallback. Hidden entirely on error or when
 *  the backend has nothing to recommend (e.g. an unseeded database). */
export function RecommendedPatterns() {
  const { user, loading: authLoading } = useAuth();
  const [recs, setRecs] = useState<Recommendations | null>(null);
  const [loading, setLoading] = useState(true);

  // Wait for the auth check so we fetch once, not once per auth transition.
  // Re-fetches on login/logout to swap between personalized and popular.
  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;
    setLoading(true);
    fetchRecommendations()
      .then((res) => {
        if (!cancelled) setRecs(res);
      })
      .catch(() => {
        if (!cancelled) setRecs(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authLoading, user?.id]);

  const showLoading = loading || authLoading;
  if (!showLoading && (!recs || recs.patterns.length === 0)) return null;

  const personalized = recs?.source === "personalized";

  return (
    <section className="recs" aria-label="Recommended patterns">
      <h2 className="recs-title">
        {showLoading ? "Finding patterns for you…" : personalized ? "Recommended for you" : "Popular right now"}
      </h2>
      {!showLoading && (
        <p className="recs-subtitle">
          {personalized
            ? "Based on your saved patterns and recent searches"
            : "Loved by the Woolly community"}
        </p>
      )}
      <ul className="recs-grid">
        {showLoading
          ? Array.from({ length: 4 }, (_, i) => (
              <li key={i}>
                <SkeletonCard />
              </li>
            ))
          : recs!.patterns.map((p) => (
              <li key={p.id}>
                <PatternCard pattern={p} />
              </li>
            ))}
      </ul>
    </section>
  );
}
