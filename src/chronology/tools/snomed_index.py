"""A local SNOMED CT search index, built once from a UMLS release.

Phrases are searched on this machine only: nothing is sent to the UMLS API,
there are no rate limits, and every result names the UMLS release it came
from, so a run can be reproduced.

``build_index`` reads ``MRCONSO.RRF`` and ``MRSTY.RRF`` (from the release zip
or an unpacked ``META`` folder), keeps the English, unsuppressed SNOMED CT US
names and writes one SQLite file. The file is licensed UMLS content: it lives
under ``data/`` (gitignored) and must never be committed or shared; each person
builds their own with their own UMLS licence. ``scripts/umls/build_snomed_index.py``
is the command-line front end.

``SnomedIndex.search`` ranks exact name matches first (ignoring case and
punctuation), then full-text matches. It returns candidates; it does not decide
which one a finding means. That is the term resolver's job.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SAB = "SNOMEDCT_US"
DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "umls"
SCHEMA_VERSION = 1

# MRCONSO.RRF columns: CUI|LAT|TS|LUI|STT|SUI|ISPREF|AUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|SRL|SUPPRESS|CVF|
_CUI, _LAT, _ISPREF, _SAB, _TTY, _CODE, _STR, _SUPPRESS = 0, 1, 6, 11, 12, 13, 14, 16
# SNOMED term types worth searching: preferred term, synonym, fully specified name.
TERM_TYPES = {"PT": 0, "SY": 1, "FN": 2}
_TAG = re.compile(r"\(([a-z][a-z /-]+)\)\s*$")  # "Neck pain (finding)" -> "finding"
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    cui: str
    code: str              # SNOMED CT concept id
    name: str              # the name that matched
    preferred_name: str    # the concept's SNOMED preferred term
    tag: str | None        # semantic tag of the fully specified name: finding, disorder, procedure ...
    semantic_types: tuple[str, ...]  # UMLS semantic types: "Sign or Symptom", ...
    match: str             # "exact" or "text"
    score: float           # 1.0 for exact; lower is worse for text matches
    release: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["semantic_types"] = list(self.semantic_types)
        return d


def normalize(text: str) -> str:
    """Lowercase words only, so 'Neck pain.' and 'neck  PAIN' compare equal."""
    return " ".join(_WORD.findall(text.lower()))


# --- building --------------------------------------------------------------

def _open_member(source: Path, name: str) -> io.TextIOBase:
    """``name`` (e.g. MRCONSO.RRF) from a release zip or a folder holding it."""
    if source.is_file() and zipfile.is_zipfile(source):
        archive = zipfile.ZipFile(source)
        members = [m for m in archive.namelist() if m.endswith("/" + name) or m == name]
        if not members:
            raise FileNotFoundError(f"{name} is not in {source.name}; download the \"UMLS Metathesaurus Full Subset\" zip, not the full release (that one needs MetamorphoSys)")
        return io.TextIOWrapper(archive.open(min(members, key=len)), encoding="utf-8")
    for path in (source / name, source / "META" / name):
        if path.exists():
            return path.open(encoding="utf-8")
    matches = sorted(source.rglob(name))
    if not matches:
        raise FileNotFoundError(f"no {name} under {source}")
    return matches[0].open(encoding="utf-8")


def guess_release(source: Path) -> str | None:
    """'2025AB' from a path such as umls-2025AB-metathesaurus-full.zip or .../2025AB/META."""
    found = re.findall(r"(?<!\d)(\d{4}A[AB])(?![A-Za-z0-9])", str(source))
    return found[-1] if found else None


def _rows(lines: Iterable[str]) -> Iterator[list[str]]:
    for line in lines:
        yield line.rstrip("\n").split("|")


def build_index(source: Path, out: Path, release: str | None = None) -> dict:
    """Write the SNOMED CT index for one UMLS release to ``out``. Returns counts."""
    release = release or guess_release(source)
    if not release:
        raise ValueError("can't tell the UMLS release from the path; pass release='2025AB'")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE names (cui TEXT, code TEXT, name TEXT, norm TEXT, tty TEXT, rank INTEGER);
        CREATE TABLE concepts (cui TEXT, code TEXT, preferred_name TEXT, tag TEXT,
                               PRIMARY KEY (cui, code));
        CREATE TABLE semtypes (cui TEXT, sty TEXT);
        CREATE VIRTUAL TABLE names_fts USING fts5(norm, content='names', content_rowid='rowid');
    """)

    names, preferred, tags, cuis = [], {}, {}, set()
    with _open_member(source, "MRCONSO.RRF") as f:
        for row in _rows(f):
            if (len(row) <= _SUPPRESS or row[_SAB] != SAB or row[_LAT] != "ENG"
                    or row[_SUPPRESS] != "N" or row[_TTY] not in TERM_TYPES):
                continue
            cui, code, text, tty = row[_CUI], row[_CODE], row[_STR], row[_TTY]
            cuis.add(cui)
            if tty == "FN":
                tag = _TAG.search(text)
                tags[(cui, code)] = tag.group(1) if tag else None
                text = _TAG.sub("", text).strip()
            elif tty == "PT" and (row[_ISPREF] == "Y" or (cui, code) not in preferred):
                preferred[(cui, code)] = text
            names.append((cui, code, text, normalize(text), tty, TERM_TYPES[tty]))
    db.executemany("INSERT INTO names VALUES (?, ?, ?, ?, ?, ?)", names)
    keys = set(preferred) | set(tags)
    db.executemany("INSERT INTO concepts VALUES (?, ?, ?, ?)",
                   [(cui, code, preferred.get((cui, code)), tags.get((cui, code))) for cui, code in keys])

    with _open_member(source, "MRSTY.RRF") as f:  # CUI|TUI|STN|STY|ATUI|CVF|
        db.executemany("INSERT INTO semtypes VALUES (?, ?)",
                       ((r[0], r[3]) for r in _rows(f) if len(r) > 3 and r[0] in cuis))

    db.executescript("""
        INSERT INTO names_fts(names_fts) VALUES ('rebuild');
        CREATE INDEX names_norm ON names(norm);
        CREATE INDEX semtypes_cui ON semtypes(cui);
    """)
    built = datetime.now(UTC).isoformat(timespec="seconds")
    counts = {"names": len(names), "concepts": len(keys), "cuis": len(cuis)}
    db.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("release", release), ("source_vocab", SAB), ("schema_version", str(SCHEMA_VERSION)),
        ("built_at", built), *((k, str(v)) for k, v in counts.items())])
    db.commit()
    db.close()
    tmp.replace(out)
    return {"release": release, **counts, "path": str(out)}


# --- searching -------------------------------------------------------------

def default_index_path(directory: Path = DEFAULT_DIR) -> Path | None:
    """The newest ``snomed_<release>.sqlite`` in ``data/umls/``, or None."""
    found = sorted(directory.glob("snomed_*.sqlite")) if directory.exists() else []
    return found[-1] if found else None


class SnomedIndex:
    """Read-only search over an index written by ``build_index``."""

    def __init__(self, path: Path):
        if not Path(path).exists():
            raise FileNotFoundError(f"no SNOMED index at {path}; build it with scripts/umls/build_snomed_index.py")
        self.path = Path(path)
        self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        meta = dict(self.db.execute("SELECT key, value FROM meta"))
        self.release = meta["release"]
        self.meta = meta

    def close(self) -> None:
        self.db.close()

    def _semtypes(self, cui: str) -> tuple[str, ...]:
        return tuple(sorted(r[0] for r in self.db.execute("SELECT sty FROM semtypes WHERE cui = ?", (cui,))))

    def _candidate(self, cui: str, code: str, name: str, match: str, score: float) -> Candidate:
        row = self.db.execute("SELECT preferred_name, tag FROM concepts WHERE cui = ? AND code = ?",
                              (cui, code)).fetchone() or (None, None)
        return Candidate(cui=cui, code=code, name=name, preferred_name=row[0] or name, tag=row[1],
                         semantic_types=self._semtypes(cui), match=match, score=score,
                         release=self.release)

    def search(self, phrase: str, max_results: int = 10,
               semantic_types: Iterable[str] | None = None) -> list[Candidate]:
        """Candidate concepts for ``phrase``, best first, one per SNOMED code.

        ``semantic_types`` keeps only concepts with at least one of those UMLS
        semantic types (e.g. {"Sign or Symptom", "Finding"}).
        """
        norm = normalize(phrase)
        if not norm:
            return []
        wanted = set(semantic_types or ())
        out: list[Candidate] = []
        seen: set[str] = set()

        def add(cui: str, code: str, name: str, match: str, score: float) -> bool:
            if code in seen:
                return False
            c = self._candidate(cui, code, name, match, score)
            if wanted and wanted.isdisjoint(c.semantic_types):
                return False
            seen.add(code)
            out.append(c)
            return len(out) >= max_results

        for cui, code, name in self.db.execute(
                "SELECT cui, code, name FROM names WHERE norm = ? ORDER BY rank, code", (norm,)):
            if add(cui, code, name, "exact", 1.0):
                return out

        query = " ".join(f'"{w}"' for w in norm.split())  # every word, in any order
        rows = self.db.execute(
            "SELECT n.cui, n.code, n.name, bm25(names_fts) AS s FROM names_fts "
            "JOIN names n ON n.rowid = names_fts.rowid WHERE names_fts MATCH ? "
            "ORDER BY s, length(n.norm), n.rank LIMIT ?", (query, max_results * 20))
        for cui, code, name, s in rows:
            # bm25 is negative and smaller is better; map it into (0, 1) below exact matches
            if add(cui, code, name, "text", round(min(0.99, -s / (1 - s)), 4)):
                break
        return out
