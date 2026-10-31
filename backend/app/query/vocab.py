"""Entity vocabulary of the *selected timetable only*, and conservative mention resolution.

Order (Intent spec §5.1): exact normalised label/id → approved alias → unique whole-word match
→ fuzzy *suggestions* (always asked, never auto-selected). Personal timetables resolve against
their own labels only; nothing is mapped to institutional records.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Domain, EntryKind, VerificationStatus
from app.models import Batch, Course, EntityAlias, Room, Staff, UserAccount
from app.services.context import SearchContext
from app.services.domains import models_for
from app.services.matching import Candidate, match, normalize_label, normalize_person

STOPWORDS = set("""a an the is are am was be to of in on at for and or my me i we you your what which who when where how show
find list all any do does did have has had class classes lecture lectures lab labs schedule timetable time today tomorrow now
next free room rooms floor professor prof dr sir madam teach teaches batch division with after before between from this that
there here it its please tell give get see check day week monday tuesday wednesday thursday friday saturday sunday am pm
details about current happening left remaining long until till much minutes hours""".split())

SESSION_SUFFIXES = ("lab", "laboratory", "tut", "tutorial", "practical", "pr", "th", "theory")

# Words that are never treated as part of a person's or subject's name when matching single words.
NAME_STOPWORDS = STOPWORDS | set("""many number count total first last latest earliest busiest most least lightest longest
shortest theory practical practicals subject subjects course courses teacher teachers professors faculty staff take takes
taking taught sir madam mam maam miss mr mrs ms college home finish start begin end done over leave morning afternoon evening
night lunch break weekend hour minute days every each per daily our us their his her him them she he they can will would
should could need want going come coming been being also only just both either not yes okay thanks open elective electives
batches group room floor busy available yesterday currently right times there some session sessions period periods
program programme engineering systems system introduction fundamentals advanced management science computer
computing data design analysis applications application technology technologies principles""".split())
_TITLE_WORDS = {"prof", "professor", "dr", "mr", "mrs", "ms", "miss", "sir", "madam", "mam", "maam", "smt", "shri"}
_SUFFIX_RX = re.compile(r"\s*\((lab|batch\s*\d+|open elective|elective)\)\s*$", re.I)


def _words(text: str | None) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def _name_words(display: str) -> set[str]:
    """Searchable words of a person's name: no titles, no initials ("Dr. Anant V. Nimkar" → anant, nimkar)."""
    return {w for w in _words(display) if len(w) >= 3 and w not in _TITLE_WORDS}


def _codes(c: Candidate) -> set[str]:
    return {x.upper() for x in c.extra.get("codes", []) if x}


def same_person(resolved: list[Candidate], pool: list[Candidate]) -> list[Candidate]:
    """One teacher can appear as a mapped staff record and as unmapped labels (the PDF legend spelled the
    name differently on another page). Entries sharing a faculty code or a name are the same person."""
    out = list(resolved)
    changed = True
    while changed:
        changed = False
        codes = set().union(*(_codes(c) for c in out)) if out else set()
        names = {normalize_person(c.display) for c in out}
        for c in pool:
            if c not in out and (_codes(c) & codes or normalize_person(c.display) in names):
                out.append(c)
                changed = True
    return out


def _people(cands: list[Candidate], pool: list[Candidate]) -> list[list[Candidate]]:
    """Group candidates into distinct people (see `same_person`)."""
    groups: list[list[Candidate]] = []
    for c in cands:
        if not any(c in g for g in groups):
            groups.append(same_person([c], pool))
    return groups


def _representative(group: list[Candidate]) -> Candidate:
    """The staff record (not an unmapped label) is shown when asking which person is meant."""
    return next((c for c in group if c.key.startswith("id:")), group[0])


def _word_eq(a: str, b: str) -> bool:
    """Exact word match, or a one-letter typo for long words ("discrete" ~ "discreate")."""
    if a == b:
        return True
    if min(len(a), len(b)) < 6 or abs(len(a) - len(b)) > 2:
        return False
    from rapidfuzz.distance import Levenshtein

    return Levenshtein.distance(a, b) <= 1


def course_base(display: str) -> str:
    name = display or ""
    while _SUFFIX_RX.search(name):
        name = _SUFFIX_RX.sub("", name)
    return name.strip().lower()


@dataclass
class Vocab:
    courses: list[Candidate] = field(default_factory=list)
    professors: list[Candidate] = field(default_factory=list)
    batches: list[Candidate] = field(default_factory=list)
    rooms: list[Candidate] = field(default_factory=list)


def _cand(kind: str, key: str, display: str, aliases: list[str], detail: str | None = None, **extra) -> Candidate:
    return Candidate(key=f"{kind}:{key}", display=display, kind=kind, detail=detail,
                     extra={"aliases": [a for a in aliases if a], **extra})


def load_vocab(db: Session, ctx: SearchContext) -> Vocab:
    m = models_for(ctx.domain)
    tid = ctx.timetable_id
    base = (m.entry.timetable_id == tid, m.entry.entry_kind == EntryKind.CLASS,
            m.entry.verification_status != VerificationStatus.REJECTED)
    v = Vocab()
    if ctx.domain == Domain.PERSONAL:
        for col, name_col, target, person in ((m.course_label, m.entry.course_name_resolved, v.courses, False),
                                              (m.staff_label, m.entry.staff_name_resolved, v.professors, True),
                                              (m.batch_label, None, v.batches, False),
                                              (m.room_label, None, v.rooms, False)):
            cols = [col] + ([name_col] if name_col is not None else [])
            for row in db.execute(select(*cols).where(*base, col.is_not(None)).distinct()):
                raw = row[0]
                name = row[1] if len(row) > 1 else None
                codes = [c for c in re.split(r"\s*\+\s*", raw) if c] if person else [raw]
                for code in codes:
                    target.append(_cand("label", normalize_label(code), name if (name and len(codes) == 1) else code,
                                        [code, raw, name if len(codes) == 1 else None], codes=[code]))
        _dedupe(v)
        return v

    aliases: dict[tuple[str, str], list[str]] = {}
    for a in db.scalars(select(EntityAlias)):
        aliases.setdefault((a.entity_type, a.entity_id), []).append(a.alias)

    # One query per entity type (no N+1): distinct label/id pairs, then the referenced master rows.
    course_rows = db.execute(select(m.entry.course_id, m.course_label, m.entry.course_name_resolved).where(*base).distinct()).all()
    staff_rows = db.execute(select(m.entry.staff_id, m.staff_label, m.entry.staff_name_resolved).where(*base).distinct()).all()
    batch_rows = db.execute(select(m.entry.batch_id, m.batch_label).where(*base).distinct()).all()
    room_rows = db.execute(select(m.entry.room_id, m.room_label).where(*base).distinct()).all()
    courses = {c.course_id: c for c in db.scalars(select(Course).where(Course.course_id.in_({r[0] for r in course_rows if r[0]})))}
    staff = {s.staff_id: (s, u) for s, u in db.execute(
        select(Staff, UserAccount).join(UserAccount, UserAccount.user_id == Staff.user_id)
        .where(Staff.staff_id.in_({r[0] for r in staff_rows if r[0]})))}
    batches = {b.batch_id: b for b in db.scalars(select(Batch).where(Batch.batch_id.in_({r[0] for r in batch_rows if r[0]})))}
    rooms = {r.room_id: r for r in db.scalars(select(Room).where(Room.room_id.in_({r[0] for r in room_rows if r[0]})))}

    for cid, raw, name in course_rows:
        if cid:
            c = courses[cid]
            v.courses.append(_cand("id", str(cid), c.name, [c.course_code, raw, name, *aliases.get(("COURSE", str(cid)), [])],
                                   c.course_code))
        elif raw:
            v.courses.append(_cand("label", normalize_label(raw), name or raw, [raw, name]))
    for sid, raw, name in staff_rows:
        if sid:
            s, u = staff[sid]
            codes = [c for c in [s.short_code, raw] if c]
            v.professors.append(_cand("id", str(sid), u.display_name, [s.short_code, raw, name, *aliases.get(("STAFF", str(sid)), [])],
                                      s.designation, codes=codes))
        elif raw:
            parts = [c for c in re.split(r"\s*\+\s*", raw) if c]
            names = [n.strip() for n in (name or "").split(",")] if name else []
            for i, code in enumerate(parts):
                disp = names[i] if len(names) == len(parts) else (name if len(parts) == 1 and name else code)
                v.professors.append(_cand("label", normalize_label(code), disp, [code, disp], code, codes=[code]))
    for bid, raw in batch_rows:
        if bid:
            b = batches[bid]
            v.batches.append(_cand("id", str(bid), b.code, [raw, *aliases.get(("BATCH", str(bid)), [])], b.cohort_label))
        elif raw:
            v.batches.append(_cand("label", normalize_label(raw), raw, [raw]))
    for rid, raw in room_rows:
        if rid:
            r = rooms[rid]
            v.rooms.append(_cand("id", str(rid), r.room_code, [raw, *aliases.get(("ROOM", str(rid)), [])],
                                 f"Floor {r.floor_label}" if r.floor_label else None))
        elif raw:
            v.rooms.append(_cand("label", normalize_label(raw), raw, [raw]))
    _dedupe(v)
    return v


def _dedupe(v: Vocab) -> None:
    for name in ("courses", "professors", "batches", "rooms"):
        seen: dict[str, Candidate] = {}
        for c in getattr(v, name):
            if c.key in seen:
                prev = seen[c.key]
                prev.extra["aliases"] = list(dict.fromkeys(prev.extra.get("aliases", []) + c.extra.get("aliases", [])))
                prev.extra["codes"] = list(dict.fromkeys(prev.extra.get("codes", []) + c.extra.get("codes", [])))
            else:
                seen[c.key] = c
        setattr(v, name, list(seen.values()))


@dataclass
class Resolution:
    resolved: list[Candidate]          # one or more candidates that together form the answer
    choices: list[Candidate]           # ambiguous → ask the user
    not_found: bool = False


def _with_session_variants(exact: list[Candidate], pool: list[Candidate]) -> list[Candidate]:
    """'DS' should also find 'DS Lab' (same subject, different session type)."""
    keys = {normalize_label(c.display) for c in exact} | {c.key.split(":", 1)[1] for c in exact if c.kind == "label"}
    out = list(exact)
    for c in pool:
        if c in out:
            continue
        labels = [normalize_label(a) for a in c.extra.get("aliases", [])] + [normalize_label(c.display)]
        if any(lab.startswith(k) and lab[len(k):] in SESSION_SUFFIXES for k in keys for lab in labels if k):
            out.append(c)
    return out


def resolve(kind: str, mention: str, vocab: Vocab, *, choice_key: str | None = None) -> Resolution:
    pool = {"course": vocab.courses, "professor": vocab.professors, "batch": vocab.batches, "room": vocab.rooms}[kind]
    person = kind == "professor"
    if choice_key:  # user picked from a clarification list: must still be in THIS timetable's vocabulary
        picked = [c for c in pool if c.key == choice_key]
        if picked and person:
            picked = same_person(picked, pool)
        return Resolution(picked, [], not picked)
    r = match(mention, pool, person=person)
    if r.exact:
        exact = r.exact
        if person:
            groups = _people(exact, pool)
            if len(groups) == 1:
                return Resolution(groups[0], [])
            return Resolution([], [_representative(g) for g in groups])
        if kind == "course":
            exact = _with_session_variants(exact, pool)
        if kind in ("course", "batch", "room") or len(exact) == 1:
            return Resolution(exact, [])
        return Resolution([], exact)
    # unique whole-word match: "desai" → "Prof. Kiran Desai" (only if exactly one such candidate)
    words = [w for w in re.split(r"[^a-z0-9]+", mention.lower()) if len(w) >= 2]
    if words:
        whole = []
        for c in pool:
            tokens = set()
            for text in [c.display, *c.extra.get("aliases", [])]:
                tokens |= {normalize_label(t) for t in re.split(r"[^A-Za-z0-9]+", text or "") if t}
            needed = [normalize_label(w) for w in words if w not in _TITLE_WORDS]
            if kind == "course":
                ok = all(any(_word_eq(w, t) for t in tokens) for w in needed)
            else:
                ok = all(w in tokens for w in needed)
            if needed and ok:
                whole.append(c)
        if person and whole:
            groups = _people(whole, pool)
            if len(groups) == 1:
                return Resolution(groups[0], [])
            return Resolution([], [_representative(g) for g in groups][:8])
        if len(whole) == 1:
            return Resolution(whole, [])
        if len(whole) > 1 and kind == "course" and len({course_base(c.display) for c in whole}) == 1:
            return Resolution(whole, [])          # one subject, several session types (theory + lab)
        if len(whole) > 1 and kind == "course" and len(words) == 1 and len(words[0]) <= 5:
            return Resolution(whole, [])          # a short family code ("MDM", "PE"): all of them
        if len(whole) > 1:
            return Resolution([], whole[:8])
    if r.suggestions:
        return Resolution([], r.suggestions)
    return Resolution([], [], True)


def scan(norm_text: str, vocab: Vocab) -> dict[str, str]:
    """Find unanchored mentions ("find all dbms classes") by exact n-gram match against the vocabulary."""
    tokens = norm_text.replace("'s", "").split()
    found: dict[str, str] = {}
    used = [False] * len(tokens)
    tables = [("batch", vocab.batches, False), ("room", vocab.rooms, False), ("course", vocab.courses, False),
              ("professor", vocab.professors, True)]
    index: dict[str, list[str]] = {}
    for kind, pool, person in tables:
        for c in pool:
            for text in [c.display, *c.extra.get("aliases", [])]:
                key = normalize_person(text) if person else normalize_label(text)
                if len(key) >= 2:
                    index.setdefault(key, [])
                    if kind not in index[key]:
                        index[key].append(kind)
    for n in (4, 3, 2, 1):
        for i in range(0, len(tokens) - n + 1):
            if any(used[i:i + n]):
                continue
            span = tokens[i:i + n]
            if n == 1 and (span[0] in STOPWORDS or len(normalize_label(span[0])) < 2):
                continue
            key = normalize_label(" ".join(span))
            kinds = index.get(key)
            if not kinds:
                continue
            for kind in kinds:
                if kind not in found:
                    found[kind] = " ".join(span)
                    for k in range(i, i + n):
                        used[k] = True
                    break
    if "professor" not in found:
        _scan_person(tokens, used, vocab, found)
    if "course" not in found:
        _scan_course(tokens, used, vocab, found)
    return found


def _scan_person(tokens: list[str], used: list[bool], vocab: Vocab, found: dict[str, str]) -> None:
    """A single word of a teacher's name ("anant", "nimkar", "devadkar"). Resolution later picks the
    unique person or asks when several share it ("sawant")."""
    index: dict[str, set[str]] = {}
    for c in vocab.professors:
        for w in _name_words(c.display):
            index.setdefault(w, set()).add(c.key)
    for i, tok in enumerate(tokens):
        word = normalize_label(tok)
        if used[i] or len(word) < 3 or word in NAME_STOPWORDS or word not in index:
            continue
        keys, span, j = index[word], [tok], i + 1
        while j < len(tokens) and not used[j] and index.get(normalize_label(tokens[j]), set()) & keys:
            keys = keys & index[normalize_label(tokens[j])]
            span.append(tokens[j])
            j += 1
        found["professor"] = " ".join(span)
        for k in range(i, j):
            used[k] = True
        return


def _scan_course(tokens: list[str], used: list[bool], vocab: Vocab, found: dict[str, str]) -> None:
    """Part of a subject's name: two or more consecutive words ("computer organization"), or one
    distinctive word that belongs to exactly one subject ("database")."""
    bases: dict[str, set[str]] = {}
    for c in vocab.courses:
        bases.setdefault(course_base(c.display), set()).update(_words(course_base(c.display)))

    def subjects(span: list[str]) -> set[str]:
        ws = [normalize_label(t) for t in span]
        return {b for b, words in bases.items() if all(any(_word_eq(w, x) for x in words) for w in ws)}

    codes: dict[str, set[str]] = {}
    for c in vocab.courses:
        for a in [c.display, *c.extra.get("aliases", [])]:
            first = _words(a)[:1]
            if first and 3 <= len(first[0]) <= 5:
                codes.setdefault(first[0], set()).add(course_base(c.display))
    for i, tok in enumerate(tokens):            # a short subject code: "mdm" → MDM-II(IOT), MDM-II(DSA) …
        w = normalize_label(tok)
        if not used[i] and w in codes and w not in NAME_STOPWORDS and w not in {"lab", "labs", "the", "and"}:
            found["course"] = tok
            used[i] = True
            return
    for n in (4, 3, 2, 1):
        for i in range(0, len(tokens) - n + 1):
            span = tokens[i:i + n]
            if any(used[i:i + n]) or any(len(normalize_label(t)) < 3 for t in span):
                continue
            if n == 1 and (len(normalize_label(span[0])) < 6 or normalize_label(span[0]) in NAME_STOPWORDS):
                continue
            if n > 1 and all(normalize_label(t) in NAME_STOPWORDS for t in span):
                continue
            hits = subjects(span)
            if hits and (n > 1 or len(hits) == 1):
                found["course"] = " ".join(span)
                for k in range(i, i + n):
                    used[k] = True
                return


def count_distinct_rooms(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Room).where(Room.is_active.is_(True))) or 0
