"""Pure parsing helpers for SIMASTER schedule data.

Kept free of any Playwright/browser dependency so they can be unit tested.
"""

from __future__ import annotations

import re

DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{2}:\d{2})-(\d{2}:\d{2})")
PAGINATION_RE = re.compile(r"view_jadwal_mengajar/(\d+)/")
_PUNCT = re.compile(r"[^a-z0-9]")
_SLUG = re.compile(r"[^a-z0-9]+")


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


def find_dosen(data, lecturer: str) -> str | None:
    """Find the dosenId in a ``list_dosen`` autocomplete payload.

    Matching is case-insensitive and ignores spaces/commas/dots so academic
    titles in either the query or the payload do not break the match.
    """
    target = _fold(lecturer)
    if not target:
        return None
    for item in data if isinstance(data, list) else []:
        name = str(
            item.get("dosenNama")
            or item.get("label")
            or item.get("value")
            or item.get("text")
            or ""
        )
        if target in _fold(name):
            return str(
                item.get("dosenId") or item.get("id") or item.get("value") or ""
            ) or None
    return None


def canonical_name(data, lecturer: str) -> str | None:
    """Return the server-side canonical lecturer name for a resolved id."""
    target = _fold(lecturer)
    if not target:
        return None
    for item in data if isinstance(data, list) else []:
        name = str(
            item.get("dosenNama")
            or item.get("label")
            or item.get("value")
            or item.get("text")
            or ""
        )
        if target in _fold(name):
            return name
    return None


def slugify(name: str) -> str:
    """'Matin Nuhamunada, S.Si., M.Sc.' -> 'matin_nuhamunada_s_si_m_sc'."""
    slug = _SLUG.sub("_", name.lower()).strip("_")
    return slug or "lecturer"
