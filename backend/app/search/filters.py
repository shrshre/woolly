"""Shared SQL filter helpers for pattern search."""

from typing import Any, Literal

DifficultyTier = Literal["beginner", "intermediate", "advanced"]

DIFFICULTY_RANGES: dict[str, tuple[float, float]] = {
    "beginner": (0.0, 3.5),
    "intermediate": (3.5, 6.5),
    "advanced": (6.5, 10.0),
}


def build_filter_clause(
    craft: str | None = None,
    difficulty: DifficultyTier | None = None,
    free: bool | None = None,
    category: str | None = None,
    *,
    prefix: str = "",
) -> tuple[str, dict[str, Any]]:
    """Return a SQL AND-fragment and bind params for pattern filters.

    ``prefix`` is prepended to column names (e.g. ``p.`` in a joined query).
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if craft:
        clauses.append(f"{prefix}craft ILIKE :craft")
        params["craft"] = craft
    if free is not None:
        clauses.append(f"{prefix}is_free = :free")
        params["free"] = free
    if category:
        clauses.append(f"{prefix}category ILIKE :category")
        params["category"] = category
    if difficulty:
        low, high = DIFFICULTY_RANGES[difficulty]
        clauses.append(
            f"{prefix}difficulty IS NOT NULL "
            f"AND CAST({prefix}difficulty AS FLOAT) > 0 "
            f"AND CAST({prefix}difficulty AS FLOAT) >= :diff_low "
            f"AND CAST({prefix}difficulty AS FLOAT) < :diff_high"
        )
        params["diff_low"] = low
        params["diff_high"] = high

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params
