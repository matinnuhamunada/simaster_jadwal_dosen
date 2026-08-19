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
    stem = f"jadwal_{slugify(lecturer)}_{semester}"
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    json_path = outdir / f"{stem}.json"
    json_path.write_text(
        json.dumps({"meta": meta, "courses": courses}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = outdir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(_flatten(courses))

    return json_path, csv_path
