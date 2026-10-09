"""Label normalisation and conservative entity matching (Intent spec §5).

Matching order: exact id → exact normalised label → approved alias → fuzzy *suggestions only*.
Fuzzy candidates are never auto-selected.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

_HONORIFICS = re.compile(r"^(prof(essor)?|dr|mr|mrs|ms|miss|smt|shri)\.?\s+", re.I)


def normalize_label(value: str | None) -> str:
    """Case/whitespace/punctuation-insensitive key. 'R-204' == 'r 204' == 'R204'."""
    if not value:
        return ""
    v = unicodedata.normalize("NFKC", value).lower().strip()
    return re.sub(r"[^0-9a-z]+", "", v)


def normalize_person(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip()
    for _ in range(2):
        v = _HONORIFICS.sub("", v)
    return normalize_label(v)


@dataclass
class Candidate:
    key: str            # what to filter entries by (raw label or entity id)
    display: str        # shown to the user when disambiguating
    kind: str = "label"  # "label" or "entity"
    score: float = 100.0
    detail: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class MatchResult:
    exact: list[Candidate]
    suggestions: list[Candidate]

    @property
    def unique(self) -> Candidate | None:
        return self.exact[0] if len(self.exact) == 1 else None


def match(query: str, candidates: list[Candidate], *, person: bool = False, fuzzy_threshold: int = 82) -> MatchResult:
    norm = normalize_person if person else normalize_label
    q = norm(query)
    if not q:
        return MatchResult([], [])
    exact: list[Candidate] = []
    seen: set[str] = set()
    for c in candidates:
        keys = {norm(c.display), norm(c.key), *(norm(a) for a in c.extra.get("aliases", []))}
        if q in keys and c.key not in seen:
            exact.append(c)
            seen.add(c.key)
    if exact:
        return MatchResult(exact, [])
    sugg: list[Candidate] = []
    for c in candidates:
        texts = [c.display, *c.extra.get("aliases", [])]
        tokens = {normalize_label(t) for txt in texts for t in re.split(r"[^A-Za-z0-9]+", txt or "") if len(t) >= 3}
        best = max(
            fuzz.ratio(q, norm(c.display)),
            fuzz.ratio(q, norm(c.key)),
            # token containment, e.g. "desai" within "kiran desai"
            100.0 if len(q) >= 4 and (q in norm(c.display)) else 0.0,
            # per-token typo tolerance, e.g. "dessai" ~ "desai" (suggestion only)
            max((fuzz.ratio(q, t) for t in tokens), default=0.0) if len(q) >= 4 else 0.0,
        )
        if best >= fuzzy_threshold:
            sugg.append(Candidate(c.key, c.display, c.kind, best, c.detail, c.extra))
    sugg.sort(key=lambda c: -c.score)
    return MatchResult([], sugg[:6])
