"""Teaching-load analysis over scraped SIMASTER schedule files.

All computation is pure Python operating on the JSON files written by the
scraper, so it can be unit-tested offline.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .parse import _fold, slugify

MEETINGS_PER_SEMESTER = 14

SUMMARY_HEADER = ["dosen", "dosenId", "total_sks", "n_classes", "status", "source_file"]
DETAIL_HEADER = [
    "dosen",
    "kode",
    "mata_kuliah",
    "kelas",
    "sks",
    "class_meetings",
    "own_meetings",
    "own_credit",
]


def _sks(raw) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _matches(entry_dosen: str, meta_dosen: str) -> bool:
    """True when two lecturer names refer to the same person.

    Case/punctuation-insensitive and tolerant of title differences in either
    direction (e.g. meta 'Matin Nuhamunada, S.Si., M.Sc.' vs an entry with
    an extra 'Ph.D.').
    """
    a, b = _fold(entry_dosen), _fold(meta_dosen)
    if not a or not b:
        return False
    return a in b or b in a


def classify(total_sks: float, min_sks: float, max_sks: float) -> str:
    if total_sks < min_sks:
        return "UNDERLOADED"
    if total_sks > max_sks:
        return "OVERLOADED"
    return "OK"


def compute_lecturer_load(courses: list[dict], dosen: str) -> dict:
    """Per-class credit for one lecturer; credit = own_meetings/14 * sks."""
    total = 0.0
    classes = []
    for c in courses:
        entries = c.get("jadwal") or []
        class_meetings = len(entries)
        own_meetings = sum(1 for e in entries if _matches(e.get("dosen", ""), dosen))
        sks = _sks(c.get("sks"))
        own_credit = own_meetings / MEETINGS_PER_SEMESTER * sks
        total += own_credit
        classes.append(
            {
                "kode": c.get("kode", ""),
                "mata_kuliah": c.get("mata_kuliah", ""),
                "kelas": c.get("kelas", ""),
                "sks": sks,
                "class_meetings": class_meetings,
                "own_meetings": own_meetings,
                "own_credit": round(own_credit, 2),
            }
        )
    return {"total_credit": round(total, 2), "n_classes": len(classes), "classes": classes}


def _load_file(path: Path) -> tuple[dict, list]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return d.get("meta", {}), d.get("courses") or []


def aggregate_loads(
    directory,
    semester: str = "20261",
    min_sks: float = 12.0,
    max_sks: float = 16.0,
    names: list[str] | None = None,
) -> dict:
    """Read every ``jadwal_*_<semester>.json`` and build the load report data.

    Dedupes by canonical `meta.dosen` (warns on duplicates), flags classes with
    a meeting count != 14, and reports expected names (from `names`, slugified)
    that have no result file as `NO_DATA`.
    """
    directory = Path(directory)
    files = sorted(directory.glob(f"jadwal_*_{semester}.json"))
    warnings: list[str] = []
    lecturers: dict[str, dict] = {}
    classes: list[dict] = []

    for f in files:
        meta, courses = _load_file(f)
        dosen = meta.get("dosen") or ""
        if not dosen:
            warnings.append(f"{f.name}: missing meta.dosen, skipped")
            continue
        key = _fold(dosen)
        if key in lecturers:
            warnings.append(
                f"duplicate result for {dosen}: {lecturers[key]['source_file']} and {f.name}"
            )
            continue
        load = compute_lecturer_load(courses, dosen)
        lecturers[key] = {
            "dosen": dosen,
            "dosenId": meta.get("dosenId"),
            "source_file": f.name,
            "total_sks": load["total_credit"],
            "n_classes": load["n_classes"],
            "status": classify(load["total_credit"], min_sks, max_sks),
        }
        for cls in load["classes"]:
            classes.append({"dosen": dosen, **cls})
            if cls["class_meetings"] != MEETINGS_PER_SEMESTER:
                warnings.append(
                    f"{dosen}: class {cls['kode']} {cls['mata_kuliah']} "
                    f"({cls['kelas']}) has {cls['class_meetings']} meetings "
                    f"(expected {MEETINGS_PER_SEMESTER})"
                )

    no_data: list[dict] = []
    if names:
        for name in names:
            slug = slugify(name)
            if not (directory / f"jadwal_{slug}_{semester}.json").exists():
                no_data.append(
                    {
                        "dosen": name,
                        "dosenId": "",
                        "total_sks": 0.0,
                        "n_classes": 0,
                        "status": "NO_DATA",
                        "source_file": "",
                    }
                )

    ordered = sorted(lecturers.values(), key=lambda r: r["total_sks"], reverse=True)
    ordered = no_data + ordered
    return {
        "lecturers": ordered,
        "classes": sorted(classes, key=lambda r: (r["dosen"], r["own_credit"]), reverse=True),
        "warnings": warnings,
        "semester": semester,
        "min_sks": min_sks,
        "max_sks": max_sks,
    }


def write_reports(result: dict, outdir=".") -> list[Path]:
    """Write load_summary.csv, load_detail.csv and load_report.md."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summary_path = outdir / "load_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_HEADER)
        for row in result["lecturers"]:
            w.writerow([row[h] for h in SUMMARY_HEADER])

    detail_path = outdir / "load_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(DETAIL_HEADER)
        for row in result["classes"]:
            w.writerow([row[h] for h in DETAIL_HEADER])

    report_path = outdir / "load_report.md"
    report_path.write_text(build_report(result), encoding="utf-8")

    return [summary_path, detail_path, report_path]


def build_report(result: dict) -> str:
    from datetime import datetime

    lines = [
        "# Teaching load report",
        "",
        f"- Semester: {result['semester']}",
        f"- Flags: `UNDERLOADED < {result['min_sks']:g} SKS`, "
        f"`OVERLOADED > {result['max_sks']:g} SKS`",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    groups = {"OVERLOADED": [], "UNDERLOADED": [], "OK": [], "NO_DATA": []}
    for row in result["lecturers"]:
        groups.setdefault(row["status"], []).append(row)

    for status in ["OVERLOADED", "UNDERLOADED", "OK", "NO_DATA"]:
        rows = groups[status]
        lines.append(f"## {status} ({len(rows)})")
        if not rows:
            lines.append("_none_")
        else:
            lines.append("| Lecturer | Total SKS | #classes |")
            lines.append("| --- | ---: | ---: |")
            for r in rows:
                lines.append(
                    f"| {r['dosen']} | {r['total_sks']:g} | {r['n_classes']} |"
                )
        lines.append("")

    lines.append(f"## Warnings ({len(result['warnings'])})")
    if result["warnings"]:
        for w in result["warnings"]:
            lines.append(f"- {w}")
    else:
        lines.append("_none_")
    lines.append("")

    lines.append(f"## Per-class detail ({len(result['classes'])})")
    lines.append("| Lecturer | kode | mata_kuliah | kelas | sks | meetings | own | credit |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
    for r in result["classes"]:
        lines.append(
            f"| {r['dosen']} | {r['kode']} | {r['mata_kuliah']} | {r['kelas']} | "
            f"{r['sks']:g} | {r['class_meetings']} | {r['own_meetings']} | {r['own_credit']:g} |"
        )
    lines.append("")
    return "\n".join(lines)