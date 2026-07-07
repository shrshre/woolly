import { useState } from "react";
import type { PatternSummary } from "../api/client";
import { Badge, difficultyVariant } from "./Badge";

export function PatternCard({ pattern }: { pattern: PatternSummary }) {
  // Local-only for now; persisting to a library arrives with user accounts (Week 4)
  const [saved, setSaved] = useState(false);
  const difficulty = difficultyVariant(pattern.difficulty);

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
              onClick={() => setSaved((s) => !s)}
            >
              <i className="ti ti-bookmark" aria-hidden="true"></i>
            </button>
            {pattern.ravelry_url && (
              <a
                className="ravelry-link"
                href={pattern.ravelry_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                View on Ravelry <i className="ti ti-external-link" aria-hidden="true"></i>
              </a>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
