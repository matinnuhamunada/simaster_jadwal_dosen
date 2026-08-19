"""Pure parsing helpers for SIMASTER schedule data.

Kept free of any Playwright/browser dependency so they can be unit tested.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{2}:\d{2})-(\d{2}:\d{2})")
PAGINATION_RE = re.compile(r"view_jadwal_mengajar/(\d+)/")
_PUNCT = re.compile(r"[^a-z0-9]")
_SLUG = re.compile(r"[^a-z0-9]+")
TERM_TITLE_RE = re.compile(r"^(?:prof|dr|dra|drs|ir)\.", re.IGNORECASE)
FUZZY_THRESHOLD = 0.6
_NAME_WORD_RE = re.compile(r"^[A-Z][a-zA-Z]{1,}$")
_TITLE_WORDS = frozenset(
    {
        "prof",
        "dr",
        "dra",
        "drs",
        "ir",
        "eng",
        "rer",
        "nat",
        "med",
        "vet",
        "biol",
        "hom",
        "drh",
        "hc",
        "dreng",
        "drmedvet",
        "drrernat",
        "drbiolhom",
    }
)


def normalize_date(dd: str, mm: str, yyyy: str) -> str:
    """'21', '08', '2026' -> '2026-08-21'."""
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


def parse_schedule_waktu(waktu: str) -> dict:
    """'Jumat 21-08-2026 07:15-08:55' -> {hari, tanggal, jam} (or raw fallback)."""
    m = DATE_RE.search(waktu)
    if m:
        return {
            "hari": waktu.split()[0] if waktu.split() else "",
            "tanggal": normalize_date(m.group(1), m.group(2), m.group(3)),
            "jam": f"{m.group(4)}-{m.group(5)}",
        }
    return {"hari": "", "tanggal": "", "jam": waktu.strip()}


def parse_table_rows(rows) -> list[dict]:
    """Turn raw table cell arrays into course records with nested schedule.

    Course rows have >= 8 cells (No, Rumpun, Jadwal Harian, Kode, Mata Kuliah,
    Kelas, SKS, Jml Mhs); each course's schedule entries follow as sibling rows
    with >= 4 cells ([seq, waktu, ruang, dosen]). Hidden ``closeData`` rows are
    still captured because the JS reader reads every ``tbody > tr``.
    """
    courses: list[dict] = []
    cur: dict | None = None
    for cells in rows:
        if len(cells) >= 8:
            cur = {
                "no": cells[0],
                "rumpun": cells[1],
                "kode": cells[3],
                "mata_kuliah": cells[4],
                "kelas": cells[5],
                "sks": cells[6],
                "jml_mhs": cells[7],
                "jadwal": [],
            }
            courses.append(cur)
        elif cur is not None and len(cells) >= 4:
            cur["jadwal"].append(
                {
                    "waktu": cells[1],
                    "ruang": cells[2],
                    "dosen": cells[3],
                }
            )
    return courses


def current_offset(page_url: str) -> int:
    """Extract the pagination offset from a URL; 0 when not paginated."""
    m = PAGINATION_RE.search(page_url or "")
    return int(m.group(1)) if m else 0


def _fold(name: str) -> str:
    return _PUNCT.sub("", name.lower())


def _is_title(token: str) -> bool:
    return _fold(token) in _TITLE_WORDS


def _name_word(token: str) -> bool:
    return bool(_NAME_WORD_RE.match(token.strip(" ,.;:()")))


def term_candidates(lecturer: str) -> list[str]:
    """Autocomplete terms to try for a lecturer, most specific first.

    Leading academic titles are skipped: a bare ``Dr.``/``Prof.`` term can
    return hundreds of candidates that exclude the target person (whose
    SIMASTER name often drops the title), letting fuzzy matching pick a wrong
    title-holder. The given name is the reliable term. A two-word variant is
    tried first when available; glued forms like ``Dr.Utaminingsih`` keep a
    title-stripped fallback.
    """
    tokens = lecturer.split()
    if not tokens:
        return []
    name_start = 0
    while name_start < len(tokens) and _is_title(tokens[name_start]):
        name_start += 1
    if name_start >= len(tokens):
        name_start = 0
    given = tokens[name_start].strip(" ,.;:()")
    candidates: list[str] = []
    if not TERM_TITLE_RE.search(given) and name_start + 1 < len(tokens) and _name_word(
        tokens[name_start + 1]
    ):
        candidates.append(f"{given} {tokens[name_start + 1].strip(' ,.;:()')}")
    candidates.append(given)
    stripped = TERM_TITLE_RE.sub("", given)
    if stripped and stripped != given and stripped not in candidates:
        candidates.append(stripped)
    return candidates


def _item_name(item) -> str:
    return str(
        item.get("dosenNama")
        or item.get("label")
        or item.get("value")
        or item.get("text")
        or ""
    )


def _item_id(item) -> str:
    return str(item.get("dosenId") or item.get("id") or item.get("value") or "")


def best_match(data, lecturer: str):
    """Resolve a lecturer to the matching autocomplete item (or None).

    Uses an exact-substring fast path (case/punctuation-insensitive) and falls
    back to fuzzy matching via ``difflib.SequenceMatcher`` so academic titles
    that differ between the source page and SIMASTER do not break resolution.
    """
    target = _fold(lecturer)
    if not target:
        return None
    items = [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []

    for item in items:
        if target in _fold(_item_name(item)):
            return item

    best, best_ratio = None, 0.0
    for item in items:
        ratio = SequenceMatcher(None, target, _fold(_item_name(item))).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    if best is not None and best_ratio >= FUZZY_THRESHOLD:
        return best
    return None


def find_dosen(data, lecturer: str) -> str | None:
    """Find the dosenId in a ``list_dosen`` autocomplete payload."""
    item = best_match(data, lecturer)
    return _item_id(item) or None if item else None


def canonical_name(data, lecturer: str) -> str | None:
    """Return the server-side canonical lecturer name for a resolved id."""
    item = best_match(data, lecturer)
    return _item_name(item) or None if item else None


def slugify(name: str) -> str:
    """'Matin Nuhamunada, S.Si., M.Sc.' -> 'matin_nuhamunada_s_si_m_sc'."""
    slug = _SLUG.sub("_", name.lower()).strip("_")
    return slug or "lecturer"
