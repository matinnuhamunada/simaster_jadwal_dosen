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

PROGRAM_LEVELS = ["S1", "S2", "S3", "PROFESI", "OTHER"]

SUMMARY_HEADER = [
    "dosen",
    "dosenId",
    "scheduled_sks",
    "est_sks",
    "sks_s1",
    "sks_s2",
    "sks_s3",
    "sks_profesi",
    "sks_unscheduled",
    "n_classes",
    "n_courses",
    "status",
    "source_file",
]
DETAIL_HEADER = [
    "dosen",
    "kode",
    "mata_kuliah",
    "rumpun",
    "level",
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


def program_level(course: dict) -> str:
    """Classify a course's program level (prodi/rumpun) as S1/S2/S3/PROFESI.

    Detected from keywords in the ``rumpun`` tag ('DOKTOR' -> S3, 'MAGISTER'
    -> S2, 'PROFESI' -> PROFESI, else 'S1' -> S1); the DOKTOR BIOLOGI ``bidb``
    kode prefix forces S3 even when ``rumpun`` disagrees or is missing (same
    fallback ``is_s3`` has always used). Anything unrecognized is ``OTHER``.
    """
    rumpun = (course.get("rumpun") or "").strip().upper()
    kode = (course.get("kode") or "").strip()
    if "DOKTOR" in rumpun or _fold(kode).startswith("bidb"):
        return "S3"
    if "MAGISTER" in rumpun:
        return "S2"
    if "PROFESI" in rumpun:
        return "PROFESI"
    if "S1" in rumpun:
        return "S1"
    return "OTHER"


def is_s3(course: dict) -> bool:
    """True for S3 (doctoral) classes."""
    return program_level(course) == "S3"


def compute_lecturer_load(courses: list[dict], dosen: str) -> dict:
    """Per-class credit for one lecturer.

    Strict credit (``total_credit``) is ``own_meetings/14 * sks``, summed only
    over classes with a fixed/booked schedule -- a class with no booked
    meetings contributes 0 and is exempted from it. Estimated credit
    (``est_sks``) instead treats such an unscheduled class as full ``sks``
    (the lecturer is assigned) and otherwise equals the strict credit.
    ``class_meetings`` comes from the clean file when present (fallback: the
    jadwal length).
    """
    total = 0.0
    est = 0.0
    unscheduled_sks = 0.0
    level_credit = {lvl: 0.0 for lvl in PROGRAM_LEVELS}
    classes = []
    for c in courses:
        entries = c.get("jadwal") or []
        class_meetings = int(c.get("class_meetings", len(entries)))
        own_meetings = sum(1 for e in entries if _matches(e.get("dosen", ""), dosen))
        sks = _sks(c.get("sks"))
        own_credit = own_meetings / MEETINGS_PER_SEMESTER * sks
        est_credit = sks if class_meetings == 0 else own_credit
        level = program_level(c)
        total += own_credit
        est += est_credit
        if class_meetings == 0:
            unscheduled_sks += est_credit
        level_credit[level] = level_credit.get(level, 0.0) + own_credit
        classes.append(
            {
                "kode": c.get("kode", ""),
                "mata_kuliah": c.get("mata_kuliah", ""),
                "rumpun": (c.get("rumpun") or "").strip(),
                "level": level,
                "kelas": c.get("kelas", ""),
                "sks": sks,
                "class_meetings": class_meetings,
                "own_meetings": own_meetings,
                "own_credit": round(own_credit, 2),
                "est_credit": round(est_credit, 2),
                "is_s3": level == "S3",
            }
        )
    return {
        "total_credit": round(total, 2),
        "est_sks": round(est, 2),
        "sks_unscheduled": round(unscheduled_sks, 2),
        "sks_s1": round(level_credit["S1"], 2),
        "sks_s2": round(level_credit["S2"], 2),
        "sks_s3": round(level_credit["S3"], 2),
        "sks_profesi": round(level_credit["PROFESI"], 2),
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
    `status` flag is banded from the strict, schedule-only SKS
    (`scheduled_sks`).
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
            "scheduled_sks": load["total_credit"],
            "est_sks": load["est_sks"],
            "sks_s1": load["sks_s1"],
            "sks_s2": load["sks_s2"],
            "sks_s3": load["sks_s3"],
            "sks_profesi": load["sks_profesi"],
            "sks_unscheduled": load["sks_unscheduled"],
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
                        "scheduled_sks": 0.0,
                        "est_sks": 0.0,
                        "sks_s1": 0.0,
                        "sks_s2": 0.0,
                        "sks_s3": 0.0,
                        "sks_profesi": 0.0,
                        "sks_unscheduled": 0.0,
                        "n_classes": 0,
                        "n_courses": 0,
                        "status": "NO_DATA",
                        "source_file": "",
                    }
                )

    ordered = sorted(lecturers.values(), key=lambda r: r["scheduled_sks"], reverse=True)
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
            lines.append(
                "| Lecturer | Scheduled SKS | Est. SKS | SKS S1 | SKS S2 | SKS S3 | "
                "SKS Profesi | #classes | #courses |"
            )
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            for r in rows:
                lines.append(
                    f"| {r['dosen']} | {r['scheduled_sks']:g} | {r['est_sks']:g} | "
                    f"{r['sks_s1']:g} | {r['sks_s2']:g} | {r['sks_s3']:g} | {r['sks_profesi']:g} | "
                    f"{r['n_classes']} | {r['n_courses']} |"
                )
        lines.append("")

    lines.append(
        "## By program level\n\n"
        "Total SKS here is the strict credit (fixed/booked schedule only; "
        "unscheduled classes are exempted, same as `scheduled_sks` above)."
    )
    level_totals = {lvl: {"n": 0, "sks": 0.0} for lvl in PROGRAM_LEVELS}
    for r in result["classes"]:
        t = level_totals.setdefault(r["level"], {"n": 0, "sks": 0.0})
        t["n"] += 1
        t["sks"] += r["own_credit"]
    lines.append("| Level | #classes | Total SKS |")
    lines.append("| --- | ---: | ---: |")
    for lvl in PROGRAM_LEVELS:
        t = level_totals[lvl]
        lines.append(f"| {lvl} | {t['n']} | {t['sks']:g} |")
    total_n = sum(t["n"] for t in level_totals.values())
    total_sks = sum(t["sks"] for t in level_totals.values())
    lines.append(f"| **TOTAL** | **{total_n}** | **{total_sks:g}** |")
    lines.append("")

    lines.append(f"## Per-class detail ({len(result['classes'])})")
    lines.append(
        "| Lecturer | kode | mata_kuliah | rumpun | level | kelas | sks | meetings | own | credit | est | s3 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in result["classes"]:
        lines.append(
            f"| {r['dosen']} | {r['kode']} | {r['mata_kuliah']} | {r['rumpun']} | "
            f"{r['level']} | {r['kelas']} | {r['sks']:g} | {r['class_meetings']} | "
            f"{r['own_meetings']} | {r['own_credit']:g} | {r['est_credit']:g} | {r['is_s3']} |"
        )
    lines.append("")

    lines.append(f"## Warnings ({len(result['warnings'])})")
    if result["warnings"]:
        for w in result["warnings"]:
            lines.append(f"- {w}")
    else:
        lines.append("_none_")
    lines.append("")
    return "\n".join(lines)