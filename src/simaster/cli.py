"""Command-line interface for the SIMASTER scraper."""

from __future__ import annotations

import argparse
import sys

import json
from difflib import SequenceMatcher
from pathlib import Path

from . import __version__
from .batch import read_lecturers
from .clean import clean_all
from .dashboard import DASHBOARD_FILENAME, DEFAULT_CALENDAR_DIR, write_dashboard
from .ics import write_ics
from .load import _matches, aggregate_loads, write_reports
from .network import build_network, filter_to_lecturers, with_scheduled_sks
from .output import verify_lecturer_output, write_outputs
from .parse import _fold
from .scraper import Scraper, SEMESTER, build_meta

# Similarity floor for the ics fuzzy name fallback (see _select_by_name).
# Real name variants (a missing/extra title, a typo) score >= 0.85 against
# the right person; a lecturer with no scraped file at all tops out <= 0.65
# against an unrelated one. 0.75 sits in the gap between those two clusters.
ICS_FUZZY_THRESHOLD = 0.75


def _scrape_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simaster",
        description="Scrape SIMASTER lecturer teaching schedules via a CDP-attached Chrome.",
    )
    parser.add_argument(
        "--lecturer",
        action="append",
        default=[],
        metavar="NAME",
        help="lecturer name to scrape (repeatable).",
    )
    parser.add_argument(
        "--names",
        action="append",
        default=[],
        metavar="FILE",
        help="text file with one lecturer name per line (blank/# lines ignored).",
    )
    parser.add_argument(
        "--semester", default=SEMESTER, help=f"semester code (default: {SEMESTER})."
    )
    parser.add_argument(
        "--outdir", default=".", help="output directory (default: current directory)."
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="CDP base URL, e.g. http://<windows-host>:9223 (default: auto-discovered gateway).",
    )
    parser.add_argument(
        "--max-login-min",
        type=int,
        default=30,
        help="minutes to wait for a manual login before giving up (default: 30).",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="print the full list_dosen responses."
    )
    parser.add_argument(
        "--from-scratch",
        action="store_true",
        help="ignore any existing output files and re-scrape every lecturer "
        "(default: verify existing outputs and only scrape what's missing/incomplete, "
        "so an interrupted run can resume where it left off).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(analyze=False)
    return parser


def _analyze_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simaster analyze",
        description="Compute teaching load (SKS) from scraped SIMASTER schedule files.",
    )
    parser.add_argument(
        "--dir",
        default="data",
        help="directory holding jadwal_*_<semester>.json files (default: data).",
    )
    parser.add_argument(
        "--semester", default=SEMESTER, help=f"semester code (default: {SEMESTER})."
    )
    parser.add_argument(
        "--min",
        dest="min_sks",
        type=float,
        default=8.0,
        help="lower edge of the ideal OK band (default: 8).",
    )
    parser.add_argument(
        "--max",
        dest="max_sks",
        type=float,
        default=16.0,
        help="overload limit; teaching above this is OVERLOADED (default: 16).",
    )
    parser.add_argument(
        "--warn",
        dest="warn_sks",
        type=float,
        default=6.0,
        help="teaching below this is a WARNING (default: 6).",
    )
    parser.add_argument(
        "--names",
        default=None,
        metavar="FILE",
        help="names file (like target.md) to report NO_DATA for missing lecturers.",
    )
    parser.add_argument(
        "--neutral",
        action="store_true",
        help="report SKS figures only; don't band lecturer load into "
        "WARNING/UNDERLOADED/OK/ABOVE/OVERLOADED-style categories. Use this "
        "when the report is meant to help lecturers manage their own "
        "schedule rather than to flag anyone's load, leaving interpretation "
        "of the numbers to the reader.",
    )
    parser.add_argument(
        "--outdir", default=".", help="output directory (default: current directory)."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(analyze=True)
    return parser


def _dashboard_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simaster dashboard",
        description="Generate a self-contained HTML teaching-load dashboard from scraped SIMASTER schedule files.",
    )
    parser.add_argument(
        "--dir",
        default="data",
        help="directory holding jadwal_*_<semester>.json files (default: data).",
    )
    parser.add_argument(
        "--semester", default=SEMESTER, help=f"semester code (default: {SEMESTER})."
    )
    parser.add_argument(
        "--min",
        dest="min_sks",
        type=float,
        default=8.0,
        help="lower edge of the ideal OK band (default: 8).",
    )
    parser.add_argument(
        "--max",
        dest="max_sks",
        type=float,
        default=16.0,
        help="overload limit; teaching above this is OVERLOADED (default: 16).",
    )
    parser.add_argument(
        "--warn",
        dest="warn_sks",
        type=float,
        default=6.0,
        help="teaching below this is a WARNING (default: 6).",
    )
    parser.add_argument(
        "--names",
        default=None,
        metavar="FILE",
        help="names file (like target.md) to report NO_DATA for missing lecturers.",
    )
    parser.add_argument(
        "--neutral",
        action="store_true",
        help="report SKS figures only; don't band lecturer load into "
        "WARNING/UNDERLOADED/OK/ABOVE/OVERLOADED-style categories. Use this "
        "when the report is meant to help lecturers manage their own "
        "schedule rather than to flag anyone's load, leaving interpretation "
        "of the numbers to the reader.",
    )
    parser.add_argument(
        "--outdir", default=".", help="output directory (default: current directory)."
    )
    parser.add_argument(
        "--filename",
        default=DASHBOARD_FILENAME,
        help=f"output HTML filename (default: {DASHBOARD_FILENAME}, so the report "
        "can be dropped straight into a static host/GitHub Pages folder).",
    )
    parser.add_argument(
        "--calendar-dir",
        dest="calendar_dir",
        default=DEFAULT_CALENDAR_DIR,
        metavar="DIR",
        help="path, relative to the dashboard HTML file once deployed, to each "
        f"lecturer's .ics file (default: {DEFAULT_CALENDAR_DIR}); used to build "
        "the per-lecturer Calendar download link. Pass an empty string to omit "
        "the links (e.g. no .ics files are being published alongside it).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(dashboard=True)
    return parser


def _ics_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simaster ics",
        description="Export a lecturer's schedule as a .ics calendar file (import into Google Calendar).",
    )
    parser.add_argument(
        "--lecturer",
        action="append",
        default=[],
        metavar="NAME",
        help="lecturer name to export, matched fuzzily against meta.dosen "
        "(repeatable). Omit both this and --names to export everyone found "
        "in --dir.",
    )
    parser.add_argument(
        "--names",
        action="append",
        default=[],
        metavar="FILE",
        help="text file with one lecturer name per line (blank/# lines ignored).",
    )
    parser.add_argument(
        "--dir",
        default="data",
        help="directory holding jadwal_*_<semester>.json files (default: data).",
    )
    parser.add_argument(
        "--semester", default=SEMESTER, help=f"semester code (default: {SEMESTER})."
    )
    parser.add_argument(
        "--outdir", default=".", help="output directory (default: current directory)."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(ics=True)
    return parser


def _clean_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simaster clean",
        description="Build a deduplicated per-lecturer dataset from raw scrape outputs.",
    )
    parser.add_argument(
        "--dir",
        default="data",
        help="directory holding raw jadwal_*_<semester>.json/.csv files (default: data).",
    )
    parser.add_argument(
        "--semester", default=SEMESTER, help=f"semester code (default: {SEMESTER})."
    )
    parser.add_argument(
        "--names",
        default=None,
        metavar="FILE",
        help="names file (like target.md); only these lecturers get clean files.",
    )
    parser.add_argument(
        "--outdir", default="data/clean", help="output directory (default: data/clean)."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(clean=True)
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "analyze":
        return _analyze_parser().parse_args(argv[1:])
    if argv and argv[0] == "dashboard":
        return _dashboard_parser().parse_args(argv[1:])
    if argv and argv[0] == "clean":
        return _clean_parser().parse_args(argv[1:])
    if argv and argv[0] == "ics":
        return _ics_parser().parse_args(argv[1:])
    return _scrape_parser().parse_args(argv)


def run_all(
    names: list[str],
    *,
    semester: str,
    outdir: str,
    endpoint: str | None,
    max_login_min: int,
    verbose: bool,
    from_scratch: bool = False,
    scraper_factory=Scraper,
) -> tuple[list, int]:
    """Scrape names one at a time, writing each lecturer's output as soon as it's done.

    Unless ``from_scratch``, lecturers with an existing, integrity-verified
    output are skipped first, so a run interrupted by a dropped connection
    can simply be re-run to resume from the last successfully scraped
    lecturer instead of starting over. Return (written_paths, failures).
    """
    written: list = []
    failures = 0

    todo = names
    if not from_scratch:
        todo = []
        for name in names:
            if verify_lecturer_output(name, semester, outdir):
                print(f"[scrape] skip '{name}': existing output verified intact.")
            else:
                todo.append(name)
    if not todo:
        return written, failures

    with scraper_factory(
        endpoint=endpoint, semester=semester, max_login_min=max_login_min, verbose=verbose
    ) as sc:
        if verbose:
            print(f"[scrape] endpoint: {sc.endpoint}")
        for name in todo:
            try:
                result = sc.scrape(name)
            except (LookupError, RuntimeError) as exc:
                print(f"[scrape] ERROR for '{name}': {exc}")
                failures += 1
                continue
            except Exception as exc:  # e.g. a dropped connection mid-scrape
                print(f"[scrape] FATAL error for '{name}': {exc}")
                print(
                    "[scrape] stopping this run; lecturers already written are safe. "
                    "Re-run the same command to resume from here."
                )
                failures += 1
                break

            if result.get("error"):
                print(f"[scrape] ERROR for '{result['lecturer']}': {result['error']}")
                failures += 1
                continue
            if not result["courses"]:
                print(f"[scrape] no courses extracted for '{result['lecturer']}'.")
                failures += 1
                continue
            meta = build_meta(result, semester)
            print(f"[scrape] {meta}")
            json_path, csv_path = write_outputs(
                result["lecturer"], semester, meta, result["courses"], outdir
            )
            written.append((json_path, csv_path))
            print(f"[scrape] wrote {json_path} and {csv_path}")
    return written, failures


def _dedupe(names: list[str]) -> list[str]:
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def run_analyze(args) -> int:
    names = read_lecturers(args.names) if args.names else None
    result = aggregate_loads(
        args.dir,
        args.semester,
        args.min_sks,
        args.max_sks,
        warn=args.warn_sks,
        names=names,
        neutral=args.neutral,
    )
    paths = write_reports(result, args.outdir)
    print(f"[analyze] {len(result['lecturers'])} lecturers, "
          f"{len(result['classes'])} class-rows, {len(result['warnings'])} warnings")
    print(f"[analyze] wrote {', '.join(str(p) for p in paths)}")
    return 0


def run_dashboard(args) -> int:
    names = read_lecturers(args.names) if args.names else None
    result = aggregate_loads(
        args.dir,
        args.semester,
        args.min_sks,
        args.max_sks,
        warn=args.warn_sks,
        names=names,
        neutral=args.neutral,
    )
    sessions_path = Path(args.dir) / "sessions.csv"
    lecturer_names = [r["dosen"] for r in result["lecturers"]]
    sks_by_dosen = {r["dosen"]: r["scheduled_sks"] for r in result["lecturers"]}
    network = None
    class_network = None
    if sessions_path.exists():
        network = with_scheduled_sks(
            filter_to_lecturers(build_network(sessions_path, unit="course"), lecturer_names),
            sks_by_dosen,
        )
        class_network = with_scheduled_sks(
            filter_to_lecturers(build_network(sessions_path, unit="kelas"), lecturer_names),
            sks_by_dosen,
        )
    path = write_dashboard(
        result,
        args.outdir,
        network=network,
        class_network=class_network,
        calendar_dir=args.calendar_dir,
        filename=args.filename,
    )
    print(f"[dashboard] {len(result['lecturers'])} lecturers, "
          f"{len(result['classes'])} class-rows, {len(result['warnings'])} warnings")
    if network:
        print(f"[dashboard] course network: {len(network['nodes'])} lecturers, {len(network['edges'])} co-teaching links")
    if class_network:
        print(f"[dashboard] class network: {len(class_network['nodes'])} lecturers, {len(class_network['edges'])} co-teaching links")
    print(f"[dashboard] wrote {path}")
    return 0


def _select_by_name(name, entries):
    """Match ``name`` against each ``(path, data)``'s ``meta.dosen``.

    Tries an exact/substring match first (via ``load._matches``); if that
    finds nothing, falls back to a whole-string similarity ratio — the same
    ``difflib.SequenceMatcher`` approach ``parse.best_match`` uses to resolve
    a scraped lecturer to SIMASTER's canonical name — since a human-typed
    roster commonly differs from meta.dosen by more than a clean prefix/
    suffix (a wrong title like "Dra." for "Dr.", a dropped "S.Si." in the
    middle, an abbreviated given name). Returns ``(matches, ratio, closest)``:
    substring match(es) -> ``(matches, None, None)``; fuzzy match at or above
    ``ICS_FUZZY_THRESHOLD`` -> ``([match], ratio, None)``; no match ->
    ``([], None, closest_dosen_seen)`` for a "did you mean" hint.
    """
    exact = [
        (path, data)
        for path, data in entries
        if _matches(name, data.get("meta", {}).get("dosen", ""))
    ]
    if exact:
        return exact, None, None

    folded = _fold(name)
    scored = sorted(
        (
            (
                SequenceMatcher(None, folded, _fold(data.get("meta", {}).get("dosen", ""))).ratio(),
                path,
                data,
            )
            for path, data in entries
        ),
        key=lambda t: t[0],
        reverse=True,
    )
    if not scored:
        return [], None, None
    ratio, path, data = scored[0]
    if ratio >= ICS_FUZZY_THRESHOLD:
        return [(path, data)], ratio, None
    return [], None, data.get("meta", {}).get("dosen", "")


def run_ics(args) -> int:
    """Export .ics files for the requested lecturers, or every lecturer found.

    Selection is by fuzzy name match against each file's ``meta.dosen`` (see
    ``_select_by_name``) rather than by reconstructing the filename from the
    given name: the slug baked into a filename comes from whatever search
    name was used at scrape time, which can diverge from meta.dosen. With
    neither --lecturer nor --names given, every jadwal_*_<semester>.json
    file in --dir is exported (same default-to-everyone convention as
    `dashboard`/`analyze`).
    """
    names = list(args.lecturer)
    for f in args.names:
        names.extend(read_lecturers(f))
    names = _dedupe(names)

    directory = Path(args.dir)
    entries = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob(f"jadwal_*_{args.semester}.json"))
    ]
    if not entries:
        print(
            f"error: no jadwal_*_{args.semester}.json files found in {directory}",
            file=sys.stderr,
        )
        return 2

    failures = 0
    if names:
        selected = []
        for name in names:
            found, ratio, closest = _select_by_name(name, entries)
            if not found:
                hint = f" (closest on file: '{closest}')" if closest else ""
                print(
                    f"[ics] ERROR for '{name}': no schedule file matches in {directory}{hint}",
                    file=sys.stderr,
                )
                failures += 1
                continue
            if ratio is not None:
                print(
                    f"[ics] '{name}' matched '{found[0][1]['meta'].get('dosen', '')}' "
                    f"({ratio:.0%} similar name)"
                )
            selected.extend(found)
    else:
        selected = entries

    for path, data in selected:
        out_path, n_events, n_skipped = write_ics(
            data.get("meta", {}), data.get("courses") or [], args.outdir
        )
        print(f"[ics] wrote {out_path} ({n_events} events, {n_skipped} skipped)")
    return 1 if failures else 0


def run_clean(args) -> int:
    names = read_lecturers(args.names) if args.names else []
    result = clean_all(args.dir, args.semester, names, outdir=args.outdir)
    print(f"[clean] aggregated {result['n_raw_sessions']} raw sessions, "
          f"removed {result['n_raw_sessions'] - result['n_sessions']} redundant "
          f"({result['n_sessions']} unique)")
    if result["sessions_file"] is not None:
        print(f"[clean] wrote {result['sessions_file']}")
    print(f"[clean] wrote {result['n_written']} clean lecturer files to {args.outdir}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if getattr(args, "analyze", False):
        return run_analyze(args)
    if getattr(args, "dashboard", False):
        return run_dashboard(args)
    if getattr(args, "clean", False):
        return run_clean(args)
    if getattr(args, "ics", False):
        return run_ics(args)

    names = list(args.lecturer)
    for f in args.names:
        names.extend(read_lecturers(f))
    if not names:
        print("error: provide at least one --lecturer NAME or --names FILE", file=sys.stderr)
        return 2

    _, failures = run_all(
        _dedupe(names),
        semester=args.semester,
        outdir=args.outdir,
        endpoint=args.endpoint,
        max_login_min=args.max_login_min,
        verbose=args.verbose,
        from_scratch=args.from_scratch,
    )
    return 1 if failures else 0