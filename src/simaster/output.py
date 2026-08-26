"""Write scraped schedule data to CSV + JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .parse import slugify

CSV_HEADER = [
    "kode",
    "mata_kuliah",
    "kelas",
    "sks",
    "jml_mhs",
    "rumpun",
    "hari",
    "tanggal",
    "jam",
    "ruang",
    "dosen",
]


def _flatten(courses: list[dict]) -> list[list]:
    rows = []
    for c in courses:
        for e in c["jadwal"]:
            rows.append(
                [
                    c["kode"],
                    c["mata_kuliah"],
                    c["kelas"],
                    c["sks"],
                    c["jml_mhs"],
                    c["rumpun"],
                    e["hari"],
                    e["tanggal"],
                    e["jam"],
                    e["ruang"],
                    e["dosen"],
                ]
            )
    return rows


def write_outputs(
    lecturer: str,
    semester: str,
    meta: dict,
    courses: list[dict],
    outdir: str | Path = ".",
) -> tuple[Path, Path]:
    """Write ``jadwal_<slug>_<semester>.json`` and ``.csv``; return their paths."""
    json_path, csv_path = output_paths(lecturer, semester, outdir)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps({"meta": meta, "courses": courses}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(_flatten(courses))

    return json_path, csv_path


def output_paths(lecturer: str, semester: str, outdir: str | Path = ".") -> tuple[Path, Path]:
    """The ``(json_path, csv_path)`` ``write_outputs`` would use for this lecturer."""
    stem = f"jadwal_{slugify(lecturer)}_{semester}"
    outdir = Path(outdir)
    return outdir / f"{stem}.json", outdir / f"{stem}.csv"


def verify_lecturer_output(lecturer: str, semester: str, outdir: str | Path = ".") -> bool:
    """Check whether a complete, self-consistent output already exists.

    Used to decide, on a resumed run, whether a lecturer can be skipped:
    both files must exist, the JSON must parse with the expected shape, its
    ``meta`` counts must match the actual course/entry data, and the CSV
    header and row count must agree with it. Any mismatch is treated as
    incomplete/corrupt, so the lecturer is re-scraped rather than trusted.
    """
    json_path, csv_path = output_paths(lecturer, semester, outdir)
    if not json_path.exists() or not csv_path.exists():
        return False

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    meta = data.get("meta")
    courses = data.get("courses")
    if not isinstance(meta, dict) or not isinstance(courses, list):
        return False
    if meta.get("semester") != semester or not meta.get("dosen"):
        return False

    total_entries = 0
    for c in courses:
        jadwal = c.get("jadwal") if isinstance(c, dict) else None
        if not isinstance(jadwal, list):
            return False
        total_entries += len(jadwal)
    if meta.get("total_courses") != len(courses):
        return False
    if meta.get("total_entries") != total_entries:
        return False

    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    except OSError:
        return False
    if not rows or rows[0] != CSV_HEADER:
        return False
    if len(rows) - 1 != total_entries:
        return False

    return True
