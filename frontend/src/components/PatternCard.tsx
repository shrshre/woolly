import { useState } from "react";
import { Link } from "react-router-dom";
import { logInteraction, type PatternSummary } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useSavedPatterns } from "../auth/SavedPatternsContext";
import { Badge, difficultyVariant } from "./Badge";

// searchEventId/position are present only when rendered from search results;
// absent on the Library page, where interaction logging is skipped.
export function PatternCard({
  pattern,
  searchEventId,
  position,
}: {
  pattern: PatternSummary;
  searchEventId?: number | null;
  position?: number;
}) {
  const { user } = useAuth();
  const { savedIds, toggleSave } = useSavedPatterns();
  const [showSignInPrompt, setShowSignInPrompt] = useState(false);

  const saved = savedIds.has(pattern.id);
  const difficulty = difficultyVariant(pattern.difficulty);

  const canLog = searchEventId != null && position != null;

  function handleSaveClick() {
    if (!user) {
      setShowSignInPrompt(true);
      return;
    }
    // Log only the save action, not unsave; fire before the async toggle.
    if (!saved && canLog) {
      logInteraction(pattern.id, {
        search_event_id: searchEventId!,
        position: position!,
        action: "save",
      });
    }
    void toggleSave(pattern.id);
  }

  function handleRavelryClick() {
    if (canLog) {
      logInteraction(pattern.id, {
        search_event_id: searchEventId!,
        position: position!,
        action: "ravelry_click",
      });
    }
  }

  return (
    <article className="card">
      <div className="card-image">
        {pattern.photo_url ? (
          <img src={pattern.photo_url} alt={pattern.name} loading="lazy" />
        ) : (
          <i className="ti ti-photo placeholder-icon" aria-hidden="true"></i>
        )}
      </div>
      <div className="card-body">
        <h3 className="card-title">{pattern.name}</h3>
        {pattern.designer && <p className="card-designer">by {pattern.designer}</p>}
        {pattern.description && <p className="card-description">{pattern.description}</p>}
        <div className="card-footer">
          <div className="card-badges">
            {difficulty && <Badge variant={difficulty.variant}>{difficulty.label}</Badge>}
            {pattern.free !== null &&
              (pattern.free ? (
                <Badge variant="free">Free</Badge>
              ) : (
                <Badge variant="paid">Paid</Badge>
              ))}
          </div>
          <div className="card-actions">
            <button
              type="button"
              className={saved ? "save-btn saved" : "save-btn"}
              aria-label={saved ? "Remove from library" : "Save to library"}
              aria-pressed={saved}
              onClick={handleSaveClick}
            >
              <i className="ti ti-bookmark" aria-hidden="true"></i>
            </button>
            {pattern.ravelry_url && (
              <a
                className="ravelry-link"
                href={pattern.ravelry_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={handleRavelryClick}
              >
                View on Ravelry <i className="ti ti-external-link" aria-hidden="true"></i>
              </a>
            )}
          </div>
        </div>
        {showSignInPrompt && !user && (
          <p className="save-prompt">
            <Link to="/login">Sign in</Link> to save patterns to your library.
          </p>
        )}
      </div>
      {pattern.rerank_score != null && (
        <>
          {pattern.relevance_label && (
            <span className="relevance-label">{pattern.relevance_label}</span>
          )}
          <div
            className="relevance-bar"
            style={{ width: `${Math.round(Math.min(Math.max(pattern.rerank_score, 0), 1) * 100)}%` }}
            aria-hidden="true"
          />
        </>
      )}
    </article>
  );
}
