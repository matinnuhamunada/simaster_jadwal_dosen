"""Command-line interface for the SIMASTER scraper."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .batch import read_lecturers
from .clean import clean_all
from .dashboard import write_dashboard
from .load import aggregate_loads, write_reports
from .output import verify_lecturer_output, write_outputs
from .scraper import Scraper, SEMESTER, build_meta


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
        "--outdir", default=".", help="output directory (default: current directory)."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.set_defaults(dashboard=True)
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
    )
    path = write_dashboard(result, args.outdir)
    print(f"[dashboard] {len(result['lecturers'])} lecturers, "
          f"{len(result['classes'])} class-rows, {len(result['warnings'])} warnings")
    print(f"[dashboard] wrote {path}")
    return 0


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