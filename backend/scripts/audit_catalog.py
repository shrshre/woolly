"""Read-only audit of the patterns catalog -> CSV report.

Checks:
  duplicate      same ravelry_url / image_url / normalized (name, designer) on 2+ rows
  missing_field  required or expected columns that are null/blank
  dead_link      ravelry_url / image_url that return 404/410, fail DNS, or are malformed

Nothing is modified: the DB session is opened read-only and links are only fetched.

Usage (from backend/):
    python scripts/audit_catalog.py                       # writes catalog_audit.csv
    python scripts/audit_catalog.py -o report.csv
    python scripts/audit_catalog.py --skip-links          # DB-only checks, no network
    python scripts/audit_catalog.py --link-limit 500      # sample the first 500 rows' links
    python scripts/audit_catalog.py --concurrency 4 --timeout 10

Dead-link statuses: 404/410/DNS/invalid are "error"; timeouts and 5xx are
"warning" (may be transient); 401/403/429 are "info" (blocked, not verifiably dead).
"""

import argparse
import asyncio
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

FIELDS = [
    "check", "severity", "pattern_id", "ravelry_id", "name",
    "field", "detail", "url", "related_ids",
]

# column -> severity when missing
REQUIRED = {"name": "error", "ravelry_url": "error"}
EXPECTED = {
    "designer": "warning", "description": "warning", "difficulty": "warning",
    "craft": "warning", "category": "warning", "image_url": "warning",
    "tags": "info",
}

QUERY = """
    SELECT id, ravelry_id, name, designer, description, difficulty, craft, category,
           ravelry_url, image_url, tags,
           embedding IS NULL AS no_embedding,
           image_embedding IS NULL AS no_image_embedding,
           raw_data IS NULL AS no_raw_data
    FROM patterns
    ORDER BY id
"""


def psycopg_dsn(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url.removeprefix(prefix)
    return url


def load_rows(dsn: str) -> list[dict]:
    conn = psycopg2.connect(dsn)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(QUERY)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def row_base(check: str, severity: str, p: dict, **kw) -> dict:
    return {
        "check": check, "severity": severity, "pattern_id": p["id"],
        "ravelry_id": p["ravelry_id"], "name": p["name"],
        "field": "", "detail": "", "url": "", "related_ids": "", **kw,
    }


def blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple)):
        return not [x for x in v if str(x).strip()]
    return False


def check_missing(rows: list[dict]) -> list[dict]:
    out = []
    for p in rows:
        for col, sev in {**REQUIRED, **EXPECTED}.items():
            if blank(p[col]):
                out.append(row_base("missing_field", sev, p, field=col, detail="null or blank"))
        if p["no_embedding"]:
            out.append(row_base("missing_field", "warning", p, field="embedding", detail="no text embedding"))
        if p["no_image_embedding"] and not blank(p["image_url"]):
            out.append(row_base("missing_field", "info", p, field="image_embedding",
                                detail="has image_url but no CLIP embedding"))
        if p["no_raw_data"]:
            out.append(row_base("missing_field", "info", p, field="raw_data", detail="null"))
    return out


def norm_text(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    parts = urlparse(u.strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def check_duplicates(rows: list[dict]) -> list[dict]:
    keys = {
        "ravelry_url": lambda p: norm_url(p["ravelry_url"]),
        "image_url": lambda p: norm_url(p["image_url"]),
        "name+designer": lambda p: (
            f"{norm_text(p['name'])}|{norm_text(p['designer'])}" if norm_text(p["name"]) else ""
        ),
    }
    out = []
    for field, keyfn in keys.items():
        groups: dict[str, list[dict]] = defaultdict(list)
        for p in rows:
            k = keyfn(p)
            if k:
                groups[k].append(p)
        for k, members in groups.items():
            if len(members) < 2:
                continue
            ids = [m["id"] for m in members]
            for m in members:
                out.append(row_base(
                    "duplicate", "error" if field == "ravelry_url" else "warning", m,
                    field=field, detail=f"{len(members)} rows share this value",
                    url=m["ravelry_url"] if field == "ravelry_url" else (m["image_url"] or "") if field == "image_url" else "",
                    related_ids=" ".join(str(i) for i in ids if i != m["id"]),
                ))
    return out


def classify(status: int) -> tuple[str, str] | None:
    """(severity, detail) for a bad HTTP status, None if the link is fine."""
    if status in (404, 410):
        return "error", f"HTTP {status}"
    if status in (401, 403, 429):
        return "info", f"HTTP {status} (blocked; not verifiably dead)"
    if status >= 500:
        return "warning", f"HTTP {status}"
    if status >= 400:
        return "warning", f"HTTP {status}"
    return None


async def probe(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "error", "malformed URL"
    try:
        r = await client.head(url)
        if r.status_code in (403, 405, 501):  # some servers reject HEAD; confirm with GET
            async with client.stream("GET", url) as g:
                return classify(g.status_code)
        return classify(r.status_code)
    except httpx.TimeoutException:
        return "warning", "timeout"
    except httpx.ConnectError as e:
        return "error", f"connection failed: {e}"
    except httpx.HTTPError as e:
        return "warning", f"{type(e).__name__}: {e}"


async def check_links(rows: list[dict], concurrency: int, timeout: float) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    cache: dict[str, tuple[str, str] | None] = {}
    out: list[dict] = []
    headers = {"User-Agent": "woolly-catalog-audit/1.0 (read-only link check)"}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        async def one(p: dict, field: str):
            url = p[field]
            if blank(url):
                return
            async with sem:
                if url not in cache:
                    cache[url] = await probe(client, url)
            res = cache[url]
            if res:
                out.append(row_base("dead_link", res[0], p, field=field, detail=res[1], url=url))

        await asyncio.gather(*(one(p, f) for p in rows for f in ("ravelry_url", "image_url")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only audit of the patterns catalog.")
    ap.add_argument("-o", "--output", default="catalog_audit.csv", help="CSV path (default catalog_audit.csv)")
    ap.add_argument("--skip-links", action="store_true", help="skip the dead-link check (no network)")
    ap.add_argument("--link-limit", type=int, default=0, help="only check links for the first N patterns")
    ap.add_argument("--concurrency", type=int, default=5, help="parallel link requests (default 5)")
    ap.add_argument("--timeout", type=float, default=15.0, help="per-request timeout seconds (default 15)")
    args = ap.parse_args()

    rows = load_rows(psycopg_dsn(get_settings().database_url))
    print(f"Loaded {len(rows)} patterns", file=sys.stderr)

    findings = check_duplicates(rows) + check_missing(rows)
    if not args.skip_links:
        subset = rows[: args.link_limit] if args.link_limit else rows
        print(f"Checking links for {len(subset)} patterns...", file=sys.stderr)
        findings += asyncio.run(check_links(subset, args.concurrency, args.timeout))

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda r: (order[r["severity"]], r["check"], r["pattern_id"], r["field"]))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(findings)

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in findings:
        counts[(r["check"], r["severity"])] += 1
    print(f"Wrote {len(findings)} findings to {args.output}", file=sys.stderr)
    for (check, sev), n in sorted(counts.items()):
        print(f"  {check:14} {sev:8} {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
