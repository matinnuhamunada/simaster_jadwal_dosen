"""Build a clean, deduplicated per-lecturer dataset from raw scrape outputs.

The raw ``jadwal_*_<semester>.json/.csv`` files list every class session in
each co-teacher's file, so the same session appears once per co-teacher file.
``clean`` aggregates all raw CSVs, deletes those redundant sessions, and writes
a clean per-lecturer JSON (own sessions only, plus assigned-but-unscheduled
classes so the SKS estimate stays correct) into a new folder (e.g.
``data/clean/``). Raw files are never modified.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .load import MEETINGS_PER_SEMESTER, _matches, _sks
from .parse import _fold, slugify

S3_RUMPUN = "[PRODI] DOKTOR BIOLOGI"


def is_s3(course: dict) -> bool:
    """True for S3 (DOKTOR BIOLOGI) classes."""
    rumpun = (course.get("rumpun") or "").strip()
    kode = (course.get("kode") or "").strip()
    return rumpun == S3_RUMPUN or _fold(kode).startswith("bidb")


def aggregate_sessions(directory, semester: str) -> tuple[list[str], list[list]]:
    """Concatenate every raw ``jadwal_*_<semester>.csv`` into one session table."""
    header: list[str] = []
    rows: list[list] = []
    for f in sorted(Path(directory).glob(f"jadwal_*_{semester}.csv")):
        with f.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            head = next(reader, None)
            if head is not None:
                header = header or head
            rows.extend(r for r in reader if r)
    return header, rows


def dedupe_sessions(rows: list[list]) -> list[list]:
    """Delete redundant sessions: identical rows (class slot + dosen) kept once."""
    seen = set()
    out = []
    for row in rows:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _class_meetings(sessions: list[list], header: list[str]) -> dict[tuple[str, str], int]:
    """Count deduplicated sessions per (kode, kelas)."""
    idx = {name: i for i, name in enumerate(header)}
    counts: dict[tuple[str, str], int] = {}
    for row in sessions:
        key = (row[idx["kode"]], row[idx["kelas"]])
        counts[key] = counts.get(key, 0) + 1
    return counts


def _unique_own_entries(entries: list[dict]) -> list[dict]:
    """Keep each of the lecturer's own sessions once (collapse within-file dupes)."""
    seen = set()
    out = []
    for e in entries:
        key = (e.get("tanggal"), e.get("jam"), e.get("ruang"), e.get("dosen"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def clean_lecturer_file(
    meta: dict, courses: list[dict], class_meetings: dict[tuple[str, str], int]
) -> dict:
    """Clean one lecturer's raw JSON: own sessions only + SKS estimation.

    Per class, the estimated credit is ``own_meetings / 14 * sks`` when the
    class has a schedule, and full ``sks`` when it has no booked meetings.
    ``est_sks_no_s3`` excludes S3 (DOKTOR BIOLOGI) classes.
    """
    dosen = meta.get("dosen") or ""
    own_entries = 0
    est_sks = 0.0
    est_sks_no_s3 = 0.0
    n_unscheduled = 0
    n_s3 = 0
    clean_courses: list[dict] = []
    for c in courses:
        sks = _sks(c.get("sks"))
        own = _unique_own_entries(
            [e for e in (c.get("jadwal") or []) if _matches(e.get("dosen", ""), dosen)]
        )
        own_meetings = len(own)
        total = class_meetings.get((c.get("kode", ""), c.get("kelas", "")), 0)
        s3 = is_s3(c)
        est = sks if total == 0 else own_meetings / MEETINGS_PER_SEMESTER * sks
        own_entries += own_meetings
        est_sks += est
        if not s3:
            est_sks_no_s3 += est
        if total == 0:
            n_unscheduled += 1
        if s3:
            n_s3 += 1
        clean_courses.append(
            {
                "no": c.get("no", ""),
                "rumpun": c.get("rumpun", ""),
                "kode": c.get("kode", ""),
                "mata_kuliah": c.get("mata_kuliah", ""),
                "kelas": c.get("kelas", ""),
                "sks": c.get("sks", ""),
                "jml_mhs": c.get("jml_mhs", ""),
                "jadwal": own,
                "class_meetings": total,
                "own_meetings": own_meetings,
            }
        )
    clean_meta = {
        **meta,
        "own_entries": own_entries,
        "est_sks": round(est_sks, 2),
        "est_sks_no_s3": round(est_sks_no_s3, 2),
        "n_unscheduled": n_unscheduled,
        "n_s3": n_s3,
    }
    return {"meta": clean_meta, "courses": clean_courses}


def clean_all(directory, semester: str, names: list[str], outdir="data/clean") -> dict:
    """Aggregate + dedupe raw CSVs, then write clean per-lecturer JSON files."""
    directory = Path(directory)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    header, rows = aggregate_sessions(directory, semester)
    sessions = dedupe_sessions(rows)

    sessions_file = outdir / "sessions.csv"
    if header:
        with sessions_file.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(sessions)

    counts = _class_meetings(sessions, header)
    written: list[Path] = []
    for name in names:
        stem = f"jadwal_{slugify(name)}_{semester}"
        raw_path = directory / f"{stem}.json"
        if not raw_path.exists():
            continue  # no raw data (NO_DATA)
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        clean = clean_lecturer_file(data.get("meta", {}), data.get("courses") or [], counts)
        out_path = outdir / f"{stem}.json"
        out_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(out_path)

    return {
        "sessions_file": sessions_file if header else None,
        "n_raw_sessions": len(rows),
        "n_sessions": len(sessions),
        "n_written": len(written),
        "written": written,
    }