"""Conversational pattern finding — the generation stage on top of search.

Two model calls per question:

  1. **Extraction** — the message (plus recent turns, so follow-ups like
     "cheaper ones?" work) becomes a clean search query plus optional
     craft/difficulty/free/category filters. The model may only choose from
     values that actually exist in the corpus, and anything it invents is
     dropped in :func:`normalize_extraction`.
  2. **Answer** — the reranked top results are packed into a numbered context
     block and the model writes a short recommendation citing them as ``[n]``.

Retrieval itself is unchanged: :func:`app.search.pipeline.search` still does
hybrid retrieval and cross-encoder reranking. Only the metadata Woolly is
allowed to store reaches the prompt — never pattern instructions — and the
prompt forbids inventing patterns or writing out directions.

Filters are treated as soft: when they retrieve nothing, the search is retried
without them and ``filters_relaxed`` is set, so an over-eager extraction turns
into "here's what's close" instead of a dead end.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Pattern
from app.search.filters import DIFFICULTY_RANGES
from app.search.pipeline import search as run_search_pipeline
from app.services import llm_service
from app.services.embedding_service import needle_sizes_from_raw, yarn_weight_from_raw
from app.services.llm_service import LLMUnavailableError

logger = logging.getLogger(__name__)

# Patterns packed into the answer prompt (and shown as cards beside it). Small
# on purpose: a short grounded shortlist reads better than a wall of options,
# and it keeps prompt cost predictable.
CITED_LIMIT = 5
# Per-pattern description budget in the context block. Enough for the model to
# judge fit; short enough that five patterns stay well inside the token budget.
CONTEXT_DESCRIPTION_CHARS = 400
CONTEXT_TAG_LIMIT = 6
# Prior turns replayed into both prompts (user + assistant messages combined).
HISTORY_TURNS = 6
# Category choices offered to the extraction model, most common first.
CATEGORY_CHOICES_LIMIT = 40

NO_RESULTS_ANSWER = (
    "I couldn't find anything in Woolly's pattern library that matches that yet. "
    "Try describing the project a little differently, or ask for something broader."
)

EXTRACTION_SYSTEM_PROMPT = """\
You turn a crafter's message into a search query for a knitting and crochet \
pattern database.

Reply with JSON only, in this shape:
{"search_query": string, "craft": string|null, "difficulty": string|null, \
"free": true|false|null, "category": string|null}

Rules:
- search_query describes what to make: the object, style, technique, yarn \
weight, or recipient. Keep it short, like a search box query.
- Do not put filter words in search_query. If you set craft, leave the words \
knitting/crochet out of it; same for free/paid and difficulty words.
- Only set a filter the crafter clearly asked for. Prefer null. A gift for a \
beginner knitter is not necessarily a beginner-difficulty pattern.
- difficulty must be exactly one of: beginner, intermediate, advanced
- craft and category must be copied exactly from the allowed values below, or \
left null. Never invent one.
- On a follow-up, carry the earlier subject forward unless the crafter changed \
it. "Cheaper ones?" after a sweater question still means sweaters, with free \
set to true.\
"""

ANSWER_SYSTEM_PROMPT = """\
You are Woolly's pattern-finding assistant, helping knitters and crocheters \
find something to make. You are warm, plain-spoken, and brief.

Rules:
- Recommend only the numbered patterns in CONTEXT. Never invent a pattern, a \
designer, a price, or a detail that is not there.
- Cite every pattern you mention as [n], using its context number.
- Never write out stitch instructions, row-by-row directions, or any part of a \
pattern's content. Woolly only holds pattern descriptions; the crafter opens \
the Ravelry link for the pattern itself.
- 2 to 4 sentences of plain prose. No headings, no bullet lists, no markdown.
- Lead with the best fit and say why it fits, using facts from CONTEXT \
(difficulty, yarn weight, category, free or paid). Mention a second option if \
it is meaningfully different.
- If the patterns are a weak match for what was asked, say so honestly rather \
than overselling them.\
"""


@dataclass
class AskOutcome:
    """Everything the API layer needs to answer, cache, and log one ask."""

    answer: str
    # Ranked pattern rows in citation order: index 0 is "[1]" in the answer.
    patterns: list[dict[str, Any]]
    search_query: str
    filters: dict[str, Any] = field(default_factory=dict)
    filters_relaxed: bool = False
    top_result_id: int | None = None
    # Which stage-1 path the pipeline took ("hybrid" or "semantic"), for logs.
    # Ask events themselves are logged under search_type "rag".
    retrieval_type: str = "hybrid"


def corpus_filter_values(db: Session) -> tuple[list[str], list[str]]:
    """Crafts and categories that exist in the seeded corpus, most common first.

    Offering these to the extraction model keeps it from inventing a category
    that would filter every pattern out.
    """
    crafts = [
        row[0]
        for row in db.query(Pattern.craft)
        .filter(Pattern.craft.isnot(None))
        .group_by(Pattern.craft)
        .order_by(func.count().desc())
        .all()
    ]
    categories = [
        row[0]
        for row in db.query(Pattern.category)
        .filter(Pattern.category.isnot(None))
        .group_by(Pattern.category)
        .order_by(func.count().desc())
        .limit(CATEGORY_CHOICES_LIMIT)
        .all()
    ]
    return crafts, categories


def _match_choice(value: Any, choices: list[str]) -> str | None:
    """Return the corpus spelling of ``value``, or None if it isn't a choice."""
    if not isinstance(value, str) or not value.strip():
        return None
    wanted = value.strip().lower()
    for choice in choices:
        if choice.lower() == wanted:
            return choice
    return None


def normalize_extraction(
    raw: dict[str, Any],
    *,
    question: str,
    crafts: list[str],
    categories: list[str],
) -> tuple[str, dict[str, Any]]:
    """Validate the extraction model's output into (search_query, filters).

    Nothing from the model is trusted: unknown crafts and categories, invalid
    difficulty tiers, and non-boolean ``free`` values are dropped rather than
    passed to the SQL filter builder. An unusable search_query falls back to
    the raw question, so a bad extraction degrades to a plain search.
    """
    query = raw.get("search_query")
    search_query = query.strip() if isinstance(query, str) and query.strip() else question.strip()

    filters: dict[str, Any] = {}

    craft = _match_choice(raw.get("craft"), crafts)
    if craft:
        filters["craft"] = craft

    category = _match_choice(raw.get("category"), categories)
    if category:
        filters["category"] = category

    difficulty = raw.get("difficulty")
    if isinstance(difficulty, str) and difficulty.strip().lower() in DIFFICULTY_RANGES:
        filters["difficulty"] = difficulty.strip().lower()

    # Strictly bool: JSON null means "not asked for", and a string "false"
    # would otherwise filter to paid patterns only.
    if isinstance(raw.get("free"), bool):
        filters["free"] = raw["free"]

    return search_query, filters


def pattern_facts(db: Session, ravelry_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Extra grounding facts for the context block, keyed by ravelry_id.

    The search pipeline's result rows carry only what the cards need, so craft,
    category, tags, and the yarn/needle details in raw_data are fetched here
    for the handful of patterns that make it into the prompt.
    """
    if not ravelry_ids:
        return {}

    rows = (
        db.query(Pattern.ravelry_id, Pattern.craft, Pattern.category, Pattern.tags, Pattern.raw_data)
        .filter(Pattern.ravelry_id.in_(ravelry_ids))
        .all()
    )
    facts = {}
    for ravelry_id, craft, category, tags, raw_data in rows:
        raw = raw_data or {}
        facts[ravelry_id] = {
            "craft": craft,
            "category": category,
            "tags": (tags or [])[:CONTEXT_TAG_LIMIT],
            "yarn_weight": yarn_weight_from_raw(raw),
            "needle_sizes": needle_sizes_from_raw(raw),
        }
    return facts


def build_context(
    patterns: list[dict[str, Any]], facts: dict[int, dict[str, Any]] | None = None
) -> str:
    """Render the numbered CONTEXT block the answer is grounded in.

    One pattern per entry, numbered from 1 so the model's ``[n]`` citations
    line up with the cards the frontend renders in the same order.
    """
    facts = facts or {}
    entries = []
    for position, pattern in enumerate(patterns, start=1):
        extra = facts.get(pattern.get("id"), {})
        attributes = [f"by {pattern.get('designer') or 'an unknown designer'}"]
        if extra.get("craft"):
            attributes.append(str(extra["craft"]))
        if extra.get("category"):
            attributes.append(str(extra["category"]))
        if pattern.get("difficulty"):
            attributes.append(f"difficulty {pattern['difficulty']}/10")
        if pattern.get("free") is not None:
            attributes.append("free" if pattern["free"] else "paid")
        if extra.get("yarn_weight"):
            attributes.append(f"{extra['yarn_weight']} weight yarn")
        if extra.get("needle_sizes"):
            attributes.append(f"needles/hook {extra['needle_sizes']}")
        if extra.get("tags"):
            attributes.append("tags: " + ", ".join(str(t) for t in extra["tags"]))

        entry = f"[{position}] {pattern.get('name')} — " + " | ".join(attributes)
        description = (pattern.get("description") or "").strip()
        if description:
            trimmed = description[:CONTEXT_DESCRIPTION_CHARS].rstrip()
            if len(description) > CONTEXT_DESCRIPTION_CHARS:
                trimmed += "..."
            entry += f"\n    {trimmed}"
        entries.append(entry)

    return "\n".join(entries)


def _recent_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """The last few turns, kept in order, with anything malformed dropped."""
    clean = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in history
        if turn.get("role") in ("user", "assistant") and turn.get("content")
    ]
    return clean[-HISTORY_TURNS:]


def build_extraction_messages(
    question: str,
    history: list[dict[str, str]],
    *,
    crafts: list[str],
    categories: list[str],
) -> list[dict[str, str]]:
    # Appended rather than interpolated: the prompt contains a literal JSON
    # example, so it is not a format string.
    system = (
        f"{EXTRACTION_SYSTEM_PROMPT}\n\n"
        f"Allowed craft values: {', '.join(crafts) or 'none — always use null'}\n"
        f"Allowed category values: {', '.join(categories) or 'none — always use null'}"
    )
    return [
        {"role": "system", "content": system},
        *_recent_history(history),
        {"role": "user", "content": question},
    ]


def build_answer_messages(
    question: str,
    history: list[dict[str, str]],
    context: str,
    *,
    filters_relaxed: bool = False,
) -> list[dict[str, str]]:
    note = (
        "\n\nNote: no pattern matched every requested filter, so these are the "
        "closest matches without those filters. Acknowledge that briefly."
        if filters_relaxed
        else ""
    )
    return [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        *_recent_history(history),
        {
            "role": "user",
            "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}{note}",
        },
    ]


async def extract_query(
    db: Session, question: str, history: list[dict[str, str]]
) -> tuple[str, dict[str, Any]]:
    """Turn the message into (search_query, filters).

    A failure here is not fatal: the question is used verbatim with no filters,
    which is exactly what the plain search bar would have done.
    """
    crafts, categories = corpus_filter_values(db)
    messages = build_extraction_messages(question, history, crafts=crafts, categories=categories)
    try:
        raw = await llm_service.complete_json(messages)
    except LLMUnavailableError:
        logger.warning("Filter extraction failed for %r; searching the question as-is.", question)
        return question, {}
    return normalize_extraction(raw, question=question, crafts=crafts, categories=categories)


async def ask(db: Session, question: str, history: list[dict[str, str]] | None = None) -> AskOutcome:
    """Answer one question with a grounded recommendation and its citations."""
    history = history or []

    search_query, filters = await extract_query(db, question, history)
    envelope = run_search_pipeline(db, search_query, **filters)

    filters_relaxed = False
    if not envelope["results"] and filters:
        logger.info("Ask %r found nothing with %s; retrying unfiltered.", search_query, filters)
        envelope = run_search_pipeline(db, search_query)
        filters_relaxed = True

    patterns = envelope["results"][:CITED_LIMIT]
    if not patterns:
        return AskOutcome(
            answer=NO_RESULTS_ANSWER,
            patterns=[],
            search_query=search_query,
            filters=filters,
            filters_relaxed=filters_relaxed,
            retrieval_type=envelope.get("search_type", "hybrid"),
        )

    context = build_context(patterns, pattern_facts(db, [p["id"] for p in patterns]))
    answer = await llm_service.complete_text(
        build_answer_messages(question, history, context, filters_relaxed=filters_relaxed)
    )

    return AskOutcome(
        answer=answer,
        patterns=patterns,
        search_query=search_query,
        filters=filters,
        filters_relaxed=filters_relaxed,
        top_result_id=envelope.get("top_result_id"),
        retrieval_type=envelope.get("search_type", "hybrid"),
    )
