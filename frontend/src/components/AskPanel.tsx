import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  askPatterns,
  type AskResult,
  type AskTurn,
  type SearchFilters,
} from "../api/client";
import { PatternCard } from "./PatternCard";
import { SkeletonCard } from "./SkeletonCard";

const ASK_SUGGESTIONS = [
  "a beginner gift I can finish this weekend",
  "cabled cardigan in worsted, nothing seamed",
  "free crochet baby blanket",
  "something to use up leftover sock yarn",
];

// Turns replayed to the server for follow-up context. Matches the backend's
// own history cap, so nothing is sent that would only be trimmed there.
const HISTORY_TURNS = 6;

function historyFrom(exchanges: AskResult[]): AskTurn[] {
  const turns: AskTurn[] = exchanges.flatMap((exchange) => [
    { role: "user" as const, content: exchange.question },
    { role: "assistant" as const, content: exchange.answer },
  ]);
  return turns.slice(-HISTORY_TURNS);
}

/** The extracted filters, as short human-readable labels. */
function filterLabels(filters: SearchFilters): string[] {
  const labels: string[] = [];
  if (filters.craft) labels.push(filters.craft);
  if (filters.category) labels.push(filters.category);
  if (filters.difficulty) labels.push(filters.difficulty);
  if (filters.free !== undefined) labels.push(filters.free ? "free" : "paid");
  return labels;
}

/** Conversational pattern finding: answers grounded in the search pipeline's
 *  results, with the cited patterns rendered as numbered cards. The whole
 *  conversation lives here in component state — nothing is stored server-side. */
export function AskPanel() {
  const [exchanges, setExchanges] = useState<AskResult[]>([]);
  const [question, setQuestion] = useState("");
  // The question currently in flight; null when idle.
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const busy = pending !== null;

  useEffect(() => {
    if (exchanges.length > 0 || busy) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [exchanges.length, busy]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    setPending(trimmed);
    setQuestion("");
    setError(null);
    try {
      const result = await askPatterns(trimmed, historyFrom(exchanges));
      setExchanges((prev) => [...prev, result]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
      // Put the question back so it can be retried without retyping.
      setQuestion(trimmed);
    } finally {
      setPending(null);
    }
  }

  function startOver() {
    setExchanges([]);
    setQuestion("");
    setError(null);
  }

  return (
    <section className="ask">
      <form
        className="search-bar ask-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(question);
        }}
      >
        <span className="search-icon">
          <i className="ti ti-message-circle" aria-hidden="true"></i>
        </span>
        <input
          type="text"
          className="search-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={
            exchanges.length > 0
              ? "Ask a follow-up, like “cheaper ones?”"
              : "Tell Woolly what you want to make"
          }
          aria-label="Ask Woolly about patterns"
          disabled={busy}
        />
        <button type="submit" className="search-submit" aria-label="Ask" disabled={busy}>
          <i className="ti ti-arrow-right" aria-hidden="true"></i>
        </button>
      </form>

      {exchanges.length === 0 && !busy && (
        <div className="chips">
          {ASK_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="chip"
              onClick={() => void send(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="ask-transcript" aria-live="polite">
        {exchanges.map((exchange, index) => (
          <article className="ask-exchange" key={`${exchange.question}-${index}`}>
            <p className="ask-question">{exchange.question}</p>

            <p className="ask-answer">{exchange.answer}</p>

            {exchange.patterns.length > 0 && (
              <>
                <p className="ask-interpretation">
                  Searched “{exchange.search_query}”
                  {filterLabels(exchange.filters_used).map((label) => (
                    <span className="ask-filter-tag" key={label}>
                      {label}
                    </span>
                  ))}
                </p>
                {exchange.filters_relaxed && (
                  <p className="ask-relaxed-note">
                    Nothing matched all of that, so these are the closest patterns without those
                    filters.
                  </p>
                )}
                <ol className="ask-citations">
                  {exchange.patterns.map((pattern, position) => (
                    <li key={pattern.id}>
                      <span className="ask-citation-num" aria-hidden="true">
                        {position + 1}
                      </span>
                      <PatternCard
                        pattern={pattern}
                        searchEventId={exchange.search_event_id}
                        position={position + 1}
                      />
                    </li>
                  ))}
                </ol>
              </>
            )}
          </article>
        ))}

        {busy && (
          <article className="ask-exchange">
            <p className="ask-question">{pending}</p>
            <p className="ask-thinking">
              <i className="ti ti-loader-2 ask-spinner" aria-hidden="true"></i>
              Looking through the pattern library…
            </p>
            <ol className="ask-citations">
              {[0, 1].map((i) => (
                <li key={i}>
                  <span className="ask-citation-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  <SkeletonCard />
                </li>
              ))}
            </ol>
          </article>
        )}

        <div ref={endRef} />
      </div>

      {error && (
        <p className="results-error" role="alert">
          {error}
        </p>
      )}

      {exchanges.length > 0 && !busy && (
        <div className="ask-footer">
          <button type="button" className="ask-reset" onClick={startOver}>
            Start a new conversation
          </button>
        </div>
      )}
    </section>
  );
}
