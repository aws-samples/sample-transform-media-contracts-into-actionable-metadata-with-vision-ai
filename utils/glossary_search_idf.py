"""
IDF Glossary Search Utility
============================
Query a glossary (list of dicts) using pure IDF (Inverse Document Frequency) scoring
with field weighting.

Documents are ranked by the sum of IDF weights for matching query tokens —
no term-frequency component, no embeddings, no heavy dependencies.

Usage:
    from glossary_search_idf import IDFGlossarySearch

    # From a JSON file
    search = IDFGlossarySearch.from_json("glossary.json")

    # With field weights (term matches rank higher)
    search = IDFGlossarySearch.from_json(
        "glossary.json",
        field_weights={"term": 5.0, "definition": 1.0},
    )

    # Or from an in-memory list
    entries = [
        {"term": "Asset", "definition": "A resource subject to a rule."},
        {"term": "Policy", "definition": "A group of rules relating to an asset."},
    ]
    search = IDFGlossarySearch(entries)

    results = search.query("who can use the asset", top_k=5)
    prompt_text = search.query_for_prompt("usage restrictions")
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


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
    """Lowercase alpha-numeric tokenizer with stop-word removal."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP_WORDS]


class IDFGlossarySearch:
    """Pure-IDF search over a list of glossary entries with field weighting."""

    DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
        "term": 3.0,
        "definition": 1.0,
        "usage_context": 1.0,
    }

    def __init__(
        self,
        entries: list[dict[str, Any]],
        field_weights: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            entries:        List of glossary dicts.
            field_weights:  Mapping of field name → multiplier.
                            Defaults to {"term": 3.0, "definition": 1.0, "usage_context": 1.0}.
                            A token found in "term" with weight 3.0 contributes 3× its IDF.
        """
        self._field_weights = field_weights or self.DEFAULT_FIELD_WEIGHTS
        self._entries = list(entries)

        # Tokenize each field separately so we can weight them
        self._field_tokens: list[dict[str, set[str]]] = []
        all_tokens: list[list[str]] = []
        for e in self._entries:
            per_field: dict[str, set[str]] = {}
            combined: list[str] = []
            for field in self._field_weights:
                tokens = _tokenize(e.get(field, "") or "")
                per_field[field] = set(tokens)
                combined.extend(tokens)
            self._field_tokens.append(per_field)
            all_tokens.append(combined)

        # Build IDF from the combined (unweighted) corpus
        n = len(all_tokens)
        df: Counter[str] = Counter()
        for tokens in all_tokens:
            df.update(set(tokens))
        self._idf: dict[str, float] = (
            {token: math.log(n / count) + 1.0 for token, count in df.items()}
            if n > 0
            else {}
        )

    # ── Constructors ────────────────────────────────────────────────

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        field_weights: dict[str, float] | None = None,
    ) -> IDFGlossarySearch:
        """Load entries from a JSON file (must be a top-level list)."""
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return cls(entries, field_weights=field_weights)

    # ── Querying ────────────────────────────────────────────────────

    def query(
        self, query: str, top_k: int = 5, normalize: bool = False
    ) -> list[dict[str, Any]]:
        """
        Return the *top_k* entries whose tokens best match *query*,
        scored by field-weighted IDF.

        A token's contribution = idf(token) × max(weight of fields it appears in).

        Args:
            query:     Search string.
            top_k:     Max results to return.
            normalize: If True, scores are scaled to 0.0–1.0.

        Each returned dict is the original entry plus a ``"score"`` key.
        """
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        # Max possible = every query token found in the highest-weighted field
        max_weight = max(self._field_weights.values())
        max_possible = (
            sum(self._idf.get(t, 0.0) for t in q_tokens) * max_weight
            if normalize
            else 1.0
        )

        scores: list[float] = []
        for field_sets in self._field_tokens:
            score = 0.0
            for t in q_tokens:
                idf = self._idf.get(t, 0.0)
                if idf == 0.0:
                    continue
                # Use the highest weight among fields that contain this token
                best = max(
                    (w for f, w in self._field_weights.items() if t in field_sets.get(f, set())),
                    default=0.0,
                )
                score += idf * best
            scores.append(score)

        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {**self._entries[i], "score": scores[i] / max_possible}
            for i in ranked
            if scores[i] > 0
        ]

    def query_for_prompt(self, query: str, top_k: int = 5) -> str:
        """Return results formatted as Markdown, ready to inject into an LLM prompt."""
        results = self.query(query, top_k)
        if not results:
            return ""
        lines = ["Relevant glossary terms:"]
        for r in results:
            lines.append(f"- **{r['term']}**: {r['definition']}")
            ctx = r.get("usage_context")
            if ctx:
                lines.append(f"  Context: {ctx}")
        return "\n".join(lines)

    # ── Introspection ───────────────────────────────────────────────

    @property
    def entries(self) -> list[dict[str, Any]]:
        """The raw glossary entries (read-only copy)."""
        return list(self._entries)

    @property
    def field_weights(self) -> dict[str, float]:
        """Active field weights."""
        return dict(self._field_weights)

    @property
    def vocab_size(self) -> int:
        """Number of unique tokens in the index."""
        return len(self._idf)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"entries={len(self)}, vocab={self.vocab_size}, "
            f"weights={self._field_weights})"
        )
