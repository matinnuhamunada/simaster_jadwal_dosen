"""Command-line interface for the SIMASTER scraper."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .batch import read_lecturers
from .output import write_outputs
from .scraper import Scraper, SEMESTER, build_meta


def parse_args(argv=None) -> argparse.Namespace:
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
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser.parse_args(argv)


def run_all(
    names: list[str],
    *,
    semester: str,
    outdir: str,
    endpoint: str | None,
    max_login_min: int,
    verbose: bool,
    scraper_factory=Scraper,
) -> tuple[list, int]:
    """Scrape all names in one browser session; return (written_paths, failures)."""
    written: list = []
    failures = 0
    with scraper_factory(
        endpoint=endpoint, semester=semester, max_login_min=max_login_min, verbose=verbose
    ) as sc:
        if verbose:
            print(f"[scrape] endpoint: {sc.endpoint}")
        results = sc.scrape_many(names)

    for result in results:
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


def main(argv=None) -> int:
    args = parse_args(argv)

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
    )
    return 1 if failures else 0