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
S3_RUMPUN = "[PRODI] DOKTOR BIOLOGI"
WARN_SKS = 6.0
OK_MIN_SKS = 8.0
OK_HIGH_SKS = 12.0
MEETING_WARN_MIN = 8
MEETING_WARN_MAX = 14

SUMMARY_HEADER = [
    "dosen",
    "dosenId",
    "total_sks",
    "est_sks",
    "est_sks_no_s3",
    "n_unscheduled",
    "n_s3",
    "n_classes",
    "n_courses",
    "status",
    "source_file",
]
DETAIL_HEADER = [
    "dosen",
    "kode",
    "mata_kuliah",
    "kelas",
    "sks",
    "class_meetings",
    "own_meetings",
    "own_credit",
    "est_credit",
    "is_s3",
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


def classify(
    credit: float,
    *,
    warn: float = WARN_SKS,
    ok_min: float = OK_MIN_SKS,
    ok_high: float = OK_HIGH_SKS,
    max_sks: float = 16.0,
) -> str:
    """Band a teaching-load credit into a status.

    The 12-SKS official minimum already includes research, so the ideal
    teaching-only band is 8-12; below 6 is a hard warning and 16 is the limit
    (which itself also covers research, community service and supporting
    activities).
    """
    if credit < warn:
        return "WARNING"
    if credit < ok_min:
        return "UNDERLOADED"
    if credit <= ok_high:
        return "OK"
    if credit <= max_sks:
        return "ABOVE"
    return "OVERLOADED"


def is_s3(course: dict) -> bool:
    """True for S3 (DOKTOR BIOLOGI) classes."""
    rumpun = (course.get("rumpun") or "").strip()
    kode = (course.get("kode") or "").strip()
    return rumpun == S3_RUMPUN or _fold(kode).startswith("bidb")


def compute_lecturer_load(courses: list[dict], dosen: str) -> dict:
    """Per-class credit for one lecturer.

    Strict credit is ``own_meetings/14 * sks``. Estimated credit treats a class
    with no booked meetings as full ``sks`` (the lecturer is assigned) and
    otherwise equals the strict credit. ``class_meetings`` comes from the clean
    file when present (fallback: the jadwal length).
    """
    total = 0.0
    est = 0.0
    est_no_s3 = 0.0
    n_unscheduled = 0
    n_s3 = 0
    classes = []
    for c in courses:
        entries = c.get("jadwal") or []
        class_meetings = int(c.get("class_meetings", len(entries)))
        own_meetings = sum(1 for e in entries if _matches(e.get("dosen", ""), dosen))
        sks = _sks(c.get("sks"))
        own_credit = own_meetings / MEETINGS_PER_SEMESTER * sks
        est_credit = sks if class_meetings == 0 else own_credit
        s3 = is_s3(c)
        total += own_credit
        est += est_credit
        if not s3:
            est_no_s3 += est_credit
        if class_meetings == 0:
            n_unscheduled += 1
        if s3:
            n_s3 += 1
        classes.append(
            {
                "kode": c.get("kode", ""),
                "mata_kuliah": c.get("mata_kuliah", ""),
                "kelas": c.get("kelas", ""),
                "sks": sks,
                "class_meetings": class_meetings,
                "own_meetings": own_meetings,
                "own_credit": round(own_credit, 2),
                "est_credit": round(est_credit, 2),
                "is_s3": s3,
            }
        )
    return {
        "total_credit": round(total, 2),
        "est_sks": round(est, 2),
        "est_sks_no_s3": round(est_no_s3, 2),
        "n_unscheduled": n_unscheduled,
        "n_s3": n_s3,
        "n_classes": len(classes),
        "n_courses": len(set(c["kode"] for c in classes)),
        "classes": classes,
    }


def _load_file(path: Path) -> tuple[dict, list]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return d.get("meta", {}), d.get("courses") or []


def aggregate_loads(
    directory,
    semester: str = "20261",
    min_sks: float = OK_MIN_SKS,
    max_sks: float = 16.0,
    warn: float = WARN_SKS,
    names: list[str] | None = None,
) -> dict:
    """Read every ``jadwal_*_<semester>.json`` and build the load report data.

    Dedupes by canonical `meta.dosen` (warns on duplicates), flags classes with
    a meeting count outside the expected 8-14 range, and reports expected names
    (from `names`, slugified) that have no result file as `NO_DATA`. The
    `status` flag is banded from the strict total SKS (`total_sks`).
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
            "est_sks": load["est_sks"],
            "est_sks_no_s3": load["est_sks_no_s3"],
            "n_unscheduled": load["n_unscheduled"],
            "n_s3": load["n_s3"],
            "n_classes": load["n_classes"],
            "n_courses": load["n_courses"],
            "status": classify(load["total_credit"], warn=warn, max_sks=max_sks),
        }
        for cls in load["classes"]:
            classes.append({"dosen": dosen, **cls})
            if cls["class_meetings"] < MEETING_WARN_MIN or cls["class_meetings"] > MEETING_WARN_MAX:
                warnings.append(
                    f"{dosen}: class {cls['kode']} {cls['mata_kuliah']} "
                    f"({cls['kelas']}) has {cls['class_meetings']} meetings "
                    f"(expected {MEETING_WARN_MIN}-{MEETING_WARN_MAX})"
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
                        "est_sks": 0.0,
                        "est_sks_no_s3": 0.0,
                        "n_unscheduled": 0,
                        "n_s3": 0,
                        "n_classes": 0,
                        "n_courses": 0,
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
        "warn_sks": warn,
        "ok_high": OK_HIGH_SKS,
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

    warn = result.get("warn_sks", WARN_SKS)
    ok_min = result.get("min_sks", OK_MIN_SKS)
    ok_high = result.get("ok_high", OK_HIGH_SKS)
    max_sks = result.get("max_sks", 16.0)
    lines = [
        "# Teaching load report",
        "",
        f"- Semester: {result['semester']}",
        f"- Status bands (teaching SKS): `WARNING < {warn:g}`, "
        f"`UNDERLOADED {warn:g}-{ok_min:g}`, `OK {ok_min:g}-{ok_high:g}`, "
        f"`ABOVE {ok_high:g}-{max_sks:g}`, `OVERLOADED > {max_sks:g}` "
        f"(the official 12-SKS minimum already includes research; 16 is the "
        f"limit and also covers research, community service and supporting "
        f"activities)",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    groups = {
        "OVERLOADED": [],
        "ABOVE": [],
        "OK": [],
        "UNDERLOADED": [],
        "WARNING": [],
        "NO_DATA": [],
    }
    for row in result["lecturers"]:
        groups.setdefault(row["status"], []).append(row)

    for status in ["OVERLOADED", "ABOVE", "OK", "UNDERLOADED", "WARNING", "NO_DATA"]:
        rows = groups[status]
        lines.append(f"## {status} ({len(rows)})")
        if not rows:
            lines.append("_none_")
        else:
            lines.append("| Lecturer | Total SKS | Est. SKS | Est. no-S3 | #classes | #courses |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
            for r in rows:
                lines.append(
                    f"| {r['dosen']} | {r['total_sks']:g} | {r['est_sks']:g} | "
                    f"{r['est_sks_no_s3']:g} | {r['n_classes']} | {r['n_courses']} |"
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
    lines.append("| Lecturer | kode | mata_kuliah | kelas | sks | meetings | own | credit | est | s3 |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in result["classes"]:
        lines.append(
            f"| {r['dosen']} | {r['kode']} | {r['mata_kuliah']} | {r['kelas']} | "
            f"{r['sks']:g} | {r['class_meetings']} | {r['own_meetings']} | "
            f"{r['own_credit']:g} | {r['est_credit']:g} | {r['is_s3']} |"
        )
    lines.append("")
    return "\n".join(lines)