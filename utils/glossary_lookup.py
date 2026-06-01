"""
Glossary Lookup Tool (for LLM tool-use)
========================================
Designed to be called BY an LLM that has identified ambiguous terms in
context and needs definitions to disambiguate.

Design assumptions:
  - The caller is an LLM, so queries are exact terms, not natural language
  - Multiple terms may be looked up in one call (batch)
  - The same term may exist in multiple glossaries (ODRL vs VFX vs legal)
  - The LLM needs ALL candidate definitions to pick the best contextual fit
  - Zero external dependencies (stdlib only)

Usage as a tool:
    from glossary_lookup import GlossaryLookup

    # Load one or more glossary files
    lookup = GlossaryLookup.from_json_files({
        "vfx":  "vpglossary_simplified.json",
        "odrl": "ODRL22_simplified.json",
    })

    # Single term
    results = lookup.lookup("pan")

    # Batch — the LLM found several unclear terms at once
    results = lookup.batch_lookup(["pan", "asset", "transfer", "dolly"])

    # Formatted for injection back into the LLM's context
    text = lookup.batch_lookup_for_prompt(["pan", "asset", "gross participation"])

Tool-call schema (for function-calling / MCP):
    {
        "name": "glossary_lookup",
        "description": "Look up entertainment/rights industry terms. Returns
            candidate definitions from multiple glossaries so you can pick
            the best fit for the current context.",
        "parameters": {
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of terms to look up"
            }
        }
    }
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ── Tokenizer ───────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through during before after above below between out off over under again "
    "further then once here there when where why how all each every both few "
    "more most other some such no nor not only own same so than too very s t d "
    "and but or if while that this these those it its he she they them their "
    "his her what which who whom".split()
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP_WORDS]


def _normalize(text: str) -> str:
    """Normalize a term for exact matching: lowercase, collapse whitespace/hyphens."""
    return re.sub(r"[\s\-_]+", " ", text.strip().lower())


# ── Lookup result ───────────────────────────────────────────────────


class LookupResult:
    """Results for a single queried term."""

    __slots__ = ("query", "exact", "fuzzy", "resolved")

    def __init__(self, query: str):
        self.query: str = query
        self.exact: list[dict[str, Any]] = []  # exact term matches
        self.fuzzy: list[dict[str, Any]] = []  # IDF-ranked fallbacks
        self.resolved: bool = False  # True if any results found

    @property
    def all_candidates(self) -> list[dict[str, Any]]:
        """Exact matches first, then fuzzy — no duplicates."""
        seen = set()
        out = []
        for entry in self.exact + self.fuzzy:
            key = entry.get("@id") or f"{entry.get('source','')}/{entry.get('term','')}"
            if key not in seen:
                seen.add(key)
                out.append(entry)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "match_type": (
                "exact" if self.exact else ("fuzzy" if self.fuzzy else "none")
            ),
            "candidates": self.all_candidates,
        }


# ── Main class ──────────────────────────────────────────────────────


class GlossaryLookup:
    """
    Multi-glossary term lookup with exact-match-first, IDF fallback.
    Designed to be called by an LLM as a tool.
    """

    def __init__(
        self,
        entries: list[dict[str, Any]],
        search_fields: tuple[str, ...] = ("term", "definition", "usage_context"),
        term_field: str = "term",
    ) -> None:
        self._entries = entries
        self._term_field = term_field
        self._search_fields = search_fields

        # ── Exact-match index: normalized_term → [entry indices]
        self._exact: dict[str, list[int]] = defaultdict(list)
        for i, e in enumerate(entries):
            term = e.get(term_field, "")
            if term:
                self._exact[_normalize(term)].append(i)

        # ── IDF index for fallback
        self._field_tokens: list[dict[str, set[str]]] = []
        all_doc_tokens: list[set[str]] = []
        for e in entries:
            per_field: dict[str, set[str]] = {}
            combined: set[str] = set()
            for field in search_fields:
                tokens = set(_tokenize(e.get(field, "") or ""))
                per_field[field] = tokens
                combined |= tokens
            self._field_tokens.append(per_field)
            all_doc_tokens.append(combined)

        n = len(entries)
        df: Counter[str] = Counter()
        for doc_tokens in all_doc_tokens:
            df.update(doc_tokens)
        self._idf: dict[str, float] = (
            {tok: math.log(n / cnt) + 1.0 for tok, cnt in df.items()} if n > 0 else {}
        )

    # ── Constructors ────────────────────────────────────────────────

    @classmethod
    def from_json_files(
        cls,
        sources: dict[str, str | Path],
        **kwargs: Any,
    ) -> GlossaryLookup:
        """
        Load multiple glossary files, tagging each entry with its source.

        Args:
            sources:  Mapping of source_label → json_file_path.
                      e.g. {"vfx": "vp.json", "odrl": "odrl.json"}
        """
        entries: list[dict[str, Any]] = []
        for label, path in sources.items():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for e in data:
                entry = dict(e)
                # Preserve original source if present, otherwise tag it
                if "source" not in entry:
                    entry["source"] = label
                entries.append(entry)
        return cls(entries, **kwargs)

    @classmethod
    def from_json(cls, path: str | Path, **kwargs: Any) -> GlossaryLookup:
        """Load a single glossary JSON (must be a top-level list)."""
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return cls(entries, **kwargs)

    # ── Single-term lookup ──────────────────────────────────────────

    def lookup(
        self,
        term: str,
        max_candidates: int = 5,
        fuzzy_threshold: float = 0.0,
    ) -> LookupResult:
        """
        Look up a single term.

        Strategy:
          1. Exact match on the term field (case-insensitive, whitespace-normalized)
          2. If no exact match, or to supplement: IDF-scored search across all fields
             with heavy boost on the term field

        Args:
            term:             The term to look up.
            max_candidates:   Max total candidates to return.
            fuzzy_threshold:  Min IDF score to include a fuzzy result (0 = include all).
        """
        result = LookupResult(query=term)
        norm = _normalize(term)

        # ── Phase 1: Exact match
        exact_indices = self._exact.get(norm, [])
        for idx in exact_indices:
            result.exact.append(self._entries[idx])

        # ── Phase 2: IDF fallback (always run — finds related terms)
        q_tokens = _tokenize(term)
        if q_tokens:
            # Score with heavy term-field weight
            weights = {
                f: (10.0 if f == self._term_field else 1.0) for f in self._search_fields
            }
            scored: list[tuple[int, float]] = []

            for i, field_sets in enumerate(self._field_tokens):
                score = 0.0
                for t in q_tokens:
                    idf = self._idf.get(t, 0.0)
                    if idf == 0.0:
                        continue
                    best_w = max(
                        (
                            w
                            for f, w in weights.items()
                            if t in field_sets.get(f, set())
                        ),
                        default=0.0,
                    )
                    score += idf * best_w
                if score > fuzzy_threshold:
                    scored.append((i, score))

            scored.sort(key=lambda x: x[1], reverse=True)

            # Normalize: max possible = every query token in the term field
            max_weight = max(weights.values())
            max_possible = sum(self._idf.get(t, 0.0) for t in q_tokens) * max_weight
            if max_possible == 0:
                max_possible = 1.0

            # Take top results, skipping exact matches already found
            exact_set = set(exact_indices)
            for idx, score in scored:
                if idx in exact_set:
                    continue
                entry = {**self._entries[idx], "_score": round(score / max_possible, 3)}
                result.fuzzy.append(entry)
                if len(result.exact) + len(result.fuzzy) >= max_candidates:
                    break

        result.resolved = bool(result.exact or result.fuzzy)
        return result

    # ── Batch lookup ────────────────────────────────────────────────

    def batch_lookup(
        self,
        terms: list[str],
        max_candidates: int = 5,
    ) -> dict[str, LookupResult]:
        """Look up multiple terms. Returns {term: LookupResult}."""
        return {t: self.lookup(t, max_candidates) for t in terms}

    # ── Prompt formatting ───────────────────────────────────────────

    def lookup_for_prompt(self, term: str, max_candidates: int = 5) -> str:
        """Look up a term, return formatted text for LLM context injection."""
        result = self.lookup(term, max_candidates)
        return self._format_result(result)

    def batch_lookup_for_prompt(
        self,
        terms: list[str],
        max_candidates: int = 5,
    ) -> str:
        """
        Batch lookup formatted for prompt injection.

        Output designed so the LLM can read it and pick the right definition
        for each term based on the surrounding context.
        """
        results = self.batch_lookup(terms, max_candidates)
        parts: list[str] = []
        for term in terms:
            parts.append(self._format_result(results[term]))
        return "\n\n".join(parts)

    def _format_result(self, result: LookupResult) -> str:
        candidates = result.all_candidates
        if not candidates:
            return f"**{result.query}**: _No definitions found._"

        lines = [f"**{result.query}**:"]
        match_type = "exact" if result.exact else "fuzzy"

        for i, c in enumerate(candidates, 1):
            source = c.get("source", "")
            source_tag = f" [{source}]" if source else ""
            is_exact = i <= len(result.exact)
            marker = "→" if is_exact else "~"

            lines.append(
                f"  {marker} {c.get('term', '?')}{source_tag}: {c.get('definition', '')}"
            )

            ctx = c.get("usage_context")
            if ctx:
                lines.append(f"    _Context: {ctx}_")

        return "\n".join(lines)

    # ── Tool-call interface (JSON in/out) ───────────────────────────

    def tool_call(
        self, terms: list[str], max_candidates: int = 5
    ) -> list[dict[str, Any]]:
        """
        JSON-serializable output for function-calling / MCP tool response.

        Returns a list of {query, match_type, candidates} dicts.
        """
        results = self.batch_lookup(terms, max_candidates)
        return [results[t].to_dict() for t in terms]

    # ── Introspection ───────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        sources = Counter(e.get("source", "unknown") for e in self._entries)
        src_str = ", ".join(f"{k}={v}" for k, v in sources.most_common())
        return f"GlossaryLookup(entries={len(self)}, sources=[{src_str}])"


# ── CLI for testing ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Glossary lookup tool")
    parser.add_argument("terms", nargs="+", help="Terms to look up")
    parser.add_argument(
        "-g",
        "--glossary",
        action="append",
        required=True,
        help="label:path pairs, e.g. -g vfx:vp.json -g odrl:odrl.json",
    )
    parser.add_argument(
        "-k", "--max", type=int, default=5, help="Max candidates per term"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    sources = {}
    for g in args.glossary:
        if ":" in g:
            label, path = g.split(":", 1)
        else:
            label = Path(g).stem
            path = g
        sources[label] = path

    lookup = GlossaryLookup.from_json_files(sources)
    print(f"# {lookup}\n")

    if args.json:
        print(json.dumps(lookup.tool_call(args.terms, args.max), indent=2))
    else:
        print(lookup.batch_lookup_for_prompt(args.terms, args.max))
