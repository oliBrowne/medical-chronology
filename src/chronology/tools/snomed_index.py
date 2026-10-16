"""A local SNOMED CT search index, built once from a UMLS release.

Normalization looks clinical phrases up in SNOMED CT. Doing that against a
local SQLite file instead of the UMLS web API means no phrase ever leaves the
machine, there are no rate limits, and every result names the exact release
it came from.

Build it once from the UMLS Metathesaurus files you download with your own
UMLS licence (https://uts.nlm.nih.gov/; the licence is per person, so each
team member builds their own copy):

    python -m chronology.tools.snomed_index build path/to/2026AA/META
    python -m chronology.tools.snomed_index search "neck pain"
    python -m chronology.tools.snomed_index info

``build`` reads ``MRCONSO.RRF`` (names), ``MRSTY.RRF`` (semantic types) and
``MRSAB.RRF`` (source versions) from the META folder, keeps the English,
non-suppressed SNOMEDCT_US rows only, and writes ``data/umls/snomed.sqlite``.
``data/`` is gitignored: the index is licensed content and must never be
committed.

Search is lexical and deterministic: an exact match on the normalized term
first, then every word matching (full-text search ranked by BM25), then any
word matching. Results can be filtered by UMLS semantic type or by the
SNOMED semantic tag (the part in brackets of a fully specified name, such as
"finding" or "disorder").
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

DEFAULT_DB = Path("data/umls/snomed.sqlite")
SAB = "SNOMEDCT_US"
SCHEMA_VERSION = "1"

# MRCONSO.RRF columns (pipe-delimited, trailing pipe)
_CUI, _LAT, _TS, _LUI, _STT, _SUI, _ISPREF, _AUI, _SAUI, _SCUI, _SDUI, _SAB, _TTY, _CODE, _STR, _SRL, \
    _SUPPRESS, _CVF = range(18)
_TAG = re.compile(r"\s\(([^()]+)\)\s*$")       # "Neck pain (finding)" -> "finding"
_WORD = re.compile(r"[a-z0-9]+")
# Term types worth searching. FN = fully specified name, PT = preferred term,
# SY = synonym; the rest are rare or redundant for lookup.
_KEEP_TTY = {"FN", "PT", "SY", "PTGB", "SYGB"}
_TTY_RANK = {"PT": 0, "FN": 1, "SY": 2, "PTGB": 3, "SYGB": 4}


def normalize(text: str) -> str:
    """Lower case, words only, single spaces: how terms are compared."""
    return " ".join(_WORD.findall(text.lower()))


@dataclass
class Candidate:
    code: str                    # SNOMED CT concept id
    cui: str                     # UMLS concept id
    name: str                    # SNOMED preferred term
    matched: str                 # the term that matched the phrase
    tag: str | None              # SNOMED semantic tag, e.g. "finding", "disorder"
    semantic_types: list[str] = field(default_factory=list)  # UMLS semantic types
    match: str = ""              # "exact" | "all_words" | "any_word"
    score: float = 0.0           # lower is better (BM25); 0 for exact matches
    release: str | None = None   # UMLS release the index was built from

    def to_dict(self) -> dict:
        return asdict(self)


# --- building ---------------------------------------------------------------

def _rows(path: Path) -> Iterator[list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        for line in f:
            yield line.rstrip("\r\n").split("|")


def _release_name(meta_dir: Path) -> str | None:
    """UMLS release ("2026AA") from release.dat next to or above META."""
    for candidate in (meta_dir / "release.dat", meta_dir.parent / "release.dat"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition("=")
                if key.strip() in ("umls.release.name", "release.name"):
                    return value.strip()
    match = re.search(r"(19|20)\d{2}A[AB]", str(meta_dir.resolve()))
    return match.group(0) if match else None


def _snomed_version(meta_dir: Path) -> str | None:
    """SNOMED CT version string from MRSAB.RRF (its SVER column)."""
    path = meta_dir / "MRSAB.RRF"
    if not path.exists():
        return None
    for row in _rows(path):
        # VCUI|RCUI|VSAB|RSAB|SON|SF|SVER|...
        if len(row) > 6 and row[3] == SAB and row[6]:
            return row[6]
    return None


def build_index(meta_dir: Path, db_path: Path = DEFAULT_DB, release: str | None = None,
                progress: bool = True) -> dict:
    """Build the SQLite index from a UMLS META folder. Returns summary counts."""
    meta_dir = Path(meta_dir)
    conso, sty = meta_dir / "MRCONSO.RRF", meta_dir / "MRSTY.RRF"
    for path in (conso, sty):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found: point build at the META folder of a UMLS release")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)

    started = time.time()
    con = sqlite3.connect(tmp)
    con.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE terms (id INTEGER PRIMARY KEY, code TEXT, cui TEXT, tty TEXT, term TEXT, norm TEXT);
        CREATE TABLE concepts (code TEXT, cui TEXT, name TEXT, fsn TEXT, tag TEXT, PRIMARY KEY (code, cui));
        CREATE TABLE semtypes (cui TEXT, tui TEXT, sty TEXT, PRIMARY KEY (cui, tui));
    """)
    names: dict[tuple[str, str], dict] = {}
    cuis: set[str] = set()
    batch, kept, read = [], 0, 0
    for row in _rows(conso):
        read += 1
        if len(row) < 17 or row[_SAB] != SAB or row[_LAT] != "ENG" or row[_SUPPRESS] != "N":
            continue
        tty = row[_TTY]
        if tty not in _KEEP_TTY:
            continue
        code, cui, term = row[_CODE], row[_CUI], row[_STR]
        key = (code, cui)
        entry = names.setdefault(key, {"name": None, "fsn": None})
        if tty == "PT" or (tty == "PTGB" and entry["name"] is None):
            entry["name"] = term
        elif tty == "FN":
            entry["fsn"] = term
        cuis.add(cui)
        batch.append((code, cui, tty, term, normalize(term)))
        kept += 1
        if len(batch) >= 50_000:
            con.executemany("INSERT INTO terms (code, cui, tty, term, norm) VALUES (?,?,?,?,?)", batch)
            batch.clear()
            if progress:
                print(f"  {read:,} rows read, {kept:,} SNOMED terms kept", file=sys.stderr)
    if batch:
        con.executemany("INSERT INTO terms (code, cui, tty, term, norm) VALUES (?,?,?,?,?)", batch)

    con.executemany(
        "INSERT INTO concepts VALUES (?,?,?,?,?)",
        [(code, cui, e["name"] or (e["fsn"] and _TAG.sub("", e["fsn"])) or "", e["fsn"],
          (_TAG.search(e["fsn"]).group(1) if e["fsn"] and _TAG.search(e["fsn"]) else None))
         for (code, cui), e in names.items()])

    sem = []
    for row in _rows(sty):
        # CUI|TUI|STN|STY|ATUI|CVF|
        if len(row) > 3 and row[0] in cuis:
            sem.append((row[0], row[1], row[3]))
    con.executemany("INSERT OR IGNORE INTO semtypes VALUES (?,?,?)", sem)

    con.executescript("""
        CREATE INDEX terms_norm ON terms (norm);
        CREATE INDEX terms_code ON terms (code, cui);
        CREATE VIRTUAL TABLE terms_fts USING fts5 (norm, content='terms', content_rowid='id',
                                                   tokenize='porter unicode61');
        INSERT INTO terms_fts (rowid, norm) SELECT id, norm FROM terms;
    """)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "source": SAB,
        "umls_release": release or _release_name(meta_dir),
        "snomed_version": _snomed_version(meta_dir),
        "built_from": str(meta_dir.resolve()),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "concepts": str(len(names)),
        "terms": str(kept),
        "seconds": str(round(time.time() - started)),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", list(summary.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()
    db_path.unlink(missing_ok=True)
    tmp.rename(db_path)
    return summary


# --- searching --------------------------------------------------------------

class SnomedIndex:
    """Read-only search over an index built by ``build_index``."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"no SNOMED index at {self.db_path}. Build it once from your UMLS download: "
                f"python -m chronology.tools.snomed_index build <path to META folder>")
        self._con = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True,
                                    check_same_thread=False)
        self.info = dict(self._con.execute("SELECT key, value FROM meta"))
        self.release = self.info.get("umls_release")

    def close(self) -> None:
        self._con.close()

    def _semtypes(self, cuis: Iterable[str]) -> dict[str, list[str]]:
        cuis = list(set(cuis))
        out: dict[str, list[str]] = {c: [] for c in cuis}
        for i in range(0, len(cuis), 500):
            chunk = cuis[i:i + 500]
            q = f"SELECT cui, sty FROM semtypes WHERE cui IN ({','.join('?' * len(chunk))}) ORDER BY sty"
            for cui, sty in self._con.execute(q, chunk):
                out[cui].append(sty)
        return out

    def _hits(self, phrase: str, limit: int) -> list[tuple[str, str, str, str, str, float]]:
        """(code, cui, term, tty, match, score) for the best term matches."""
        norm = normalize(phrase)
        if not norm:
            return []
        rows = [(c, u, t, y, "exact", 0.0) for c, u, t, y in self._con.execute(
            "SELECT code, cui, term, tty FROM terms WHERE norm = ?", (norm,))]
        words = norm.split()
        for match, joiner in (("all_words", " AND "), ("any_word", " OR ")):
            if len(rows) >= limit or (match == "any_word" and len(words) == 1):
                break
            query = joiner.join(f'"{w}"' for w in words)
            rows += [(c, u, t, y, match, s) for c, u, t, y, s in self._con.execute(
                "SELECT t.code, t.cui, t.term, t.tty, bm25(terms_fts) AS s FROM terms_fts "
                "JOIN terms t ON t.id = terms_fts.rowid WHERE terms_fts MATCH ? "
                "ORDER BY s LIMIT ?", (query, limit * 20))]
        return rows

    def search(self, phrase: str, limit: int = 10, semantic_types: Iterable[str] | None = None,
               tags: Iterable[str] | None = None) -> list[Candidate]:
        """Best SNOMED concepts for a clinical phrase, best first, one per concept."""
        wanted_sty = {s.lower() for s in semantic_types} if semantic_types else None
        wanted_tag = {t.lower() for t in tags} if tags else None
        order = {"exact": 0, "all_words": 1, "any_word": 2}
        best: dict[tuple[str, str], tuple] = {}
        for code, cui, term, tty, match, score in self._hits(phrase, limit):
            key = (code, cui)
            rank = (order[match], score, _TTY_RANK.get(tty, 9), len(term))
            if key not in best or rank < best[key][0]:
                best[key] = (rank, term, match, score)
        if not best:
            return []
        sty = self._semtypes(cui for _, cui in best)
        concepts = {}
        keys = list(best)
        for i in range(0, len(keys), 300):
            chunk = keys[i:i + 300]
            q = ("SELECT code, cui, name, tag FROM concepts WHERE "
                 + " OR ".join("(code = ? AND cui = ?)" for _ in chunk))
            for code, cui, name, tag in self._con.execute(q, [x for k in chunk for x in k]):
                concepts[(code, cui)] = (name, tag)
        out = []
        for key, (rank, term, match, score) in sorted(best.items(), key=lambda kv: kv[1][0]):
            name, tag = concepts.get(key, (term, None))
            types = sty.get(key[1], [])
            if wanted_sty and not wanted_sty & {s.lower() for s in types}:
                continue
            if wanted_tag and (tag or "").lower() not in wanted_tag:
                continue
            out.append(Candidate(code=key[0], cui=key[1], name=name, matched=term, tag=tag,
                                 semantic_types=types, match=match, score=round(score, 4),
                                 release=self.release))
            if len(out) >= limit:
                break
        return out

    def concept(self, code: str) -> dict | None:
        """Everything the index holds for one SNOMED code."""
        rows = self._con.execute("SELECT code, cui, name, fsn, tag FROM concepts WHERE code = ?",
                                 (code,)).fetchall()
        if not rows:
            return None
        code, cui, name, fsn, tag = rows[0]
        terms = [t for (t,) in self._con.execute(
            "SELECT DISTINCT term FROM terms WHERE code = ? ORDER BY term", (code,))]
        return {"code": code, "cui": cui, "name": name, "fsn": fsn, "tag": tag,
                "semantic_types": self._semtypes([cui])[cui], "terms": terms,
                "release": self.release}


# --- command line -----------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the index from a UMLS META folder")
    b.add_argument("meta_dir", type=Path)
    b.add_argument("--db", type=Path, default=DEFAULT_DB)
    b.add_argument("--release", help="UMLS release name, if it cannot be read from release.dat")
    s = sub.add_parser("search", help="look a phrase up")
    s.add_argument("phrase")
    s.add_argument("--db", type=Path, default=DEFAULT_DB)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--tag", action="append", help="SNOMED semantic tag filter, e.g. finding")
    s.add_argument("--sty", action="append", help="UMLS semantic type filter, e.g. 'Sign or Symptom'")
    i = sub.add_parser("info", help="show what the index was built from")
    i.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.cmd == "build":
        summary = build_index(args.meta_dir, args.db, args.release)
        print(json.dumps(summary, indent=1))
    elif args.cmd == "search":
        index = SnomedIndex(args.db)
        for c in index.search(args.phrase, args.limit, semantic_types=args.sty, tags=args.tag):
            print(f"{c.code:>12}  {c.cui}  {c.name}  [{c.tag or '-'}]  ({c.match}: {c.matched!r}; "
                  f"{', '.join(c.semantic_types)})")
    else:
        print(json.dumps(SnomedIndex(args.db).info, indent=1))


if __name__ == "__main__":
    main()
