"""Recorded model completions, so the Ask suite runs without an API key.

Every chat completion goes through ``llm_service._complete``. While a
:class:`CompletionRecorder` is installed, that function is swapped for one that
keys each request by a hash of everything that affects the reply (model,
messages, token limit, temperature, JSON mode):

    replay  answer from the fixture file; a missing key fails the case
    record  replay what's recorded, call the live model for the rest, and save.
            Unchanged prompts keep their reply (and its hand judgment); delete
            the file for a full re-record.
    live    call the live model for everything and save nothing

A replayed reply is only valid for the exact prompt it was recorded with. A
change to a prompt, the corpus, or retrieval changes the context block, so the
key misses and the case errors with "re-record", instead of scoring an answer
to a question that was never asked.
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

LLM_MODES = ("replay", "record", "live")


class FixtureMissing(RuntimeError):
    """Replay found no recorded reply. Not an LLMUnavailableError on purpose:
    Ask degrades gracefully on that error, which would hide a stale fixture."""


def request_key(model: str, messages: list[dict[str, str]], *, max_tokens: int, temperature: float, json_mode: bool) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "json_mode": json_mode,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class CompletionRecorder:
    path: Path
    mode: str = "replay"
    model: str = ""
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    case_id: str = ""
    used: set[str] = field(default_factory=set)
    cases_run: set[str] = field(default_factory=set)
    hits: int = 0
    misses: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        if self.mode not in LLM_MODES:
            raise ValueError(f"unknown llm mode {self.mode!r}")
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.entries[entry["key"]] = entry

    def start_case(self, case_id: str) -> None:
        self.case_id = case_id
        self.cases_run.add(case_id)

    async def complete(self, live, messages, *, max_tokens: int, temperature: float, json_mode: bool) -> str:
        key = request_key(self.model, messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode)
        self.used.add(key)
        entry = self.entries.get(key)
        if self.mode == "record" and entry is not None:
            self.hits += 1
            return entry["response"]
        if self.mode == "replay":
            if entry is None:
                self.misses += 1
                raise FixtureMissing(
                    "no recorded completion for this prompt; the prompt, corpus, or retrieval changed. "
                    "Re-record with --llm record"
                )
            self.hits += 1
            return entry["response"]

        self.calls += 1
        response = await live(messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode)
        if self.mode == "record":
            self.entries[key] = {
                "key": key,
                "case": self.case_id,
                "model": self.model,
                "json_mode": json_mode,
                "response": response,
            }
        return response

    def save(self) -> int:
        """Write the fixture file. Entries recorded for a case that just ran but
        weren't used this time are stale and dropped. Returns entries written."""
        kept = [
            entry
            for key, entry in self.entries.items()
            if key in self.used or entry.get("case") not in self.cases_run
        ]
        kept.sort(key=lambda e: (e.get("case", ""), e["key"]))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept), encoding="utf-8")
        return len(kept)

    @contextmanager
    def installed(self) -> Iterator["CompletionRecorder"]:
        from app.services import llm_service

        live = llm_service._complete

        async def patched(messages, *, max_tokens, temperature, json_mode):
            return await self.complete(
                live, messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode
            )

        llm_service._complete = patched
        try:
            yield self
        finally:
            llm_service._complete = live
