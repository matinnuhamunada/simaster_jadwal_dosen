"""Lecturer co-teaching network built from the faculty-wide session catalog.

Unlike ``load.aggregate_loads`` (which reads the per-lecturer clean files,
where co-teachers are stripped to own-sessions-only), this reads
``sessions.csv`` directly -- the one file that still has one row per
(session, dosen) pair -- so a co-teacher who was never a scrape target still
gets a correct node.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .load import PROGRAM_LEVELS, program_level
from .parse import _fold

_LEVEL_RANK = {level: i for i, level in enumerate(PROGRAM_LEVELS)}


def _read_sessions(path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.DictReader(f) if row.get("dosen")]


def build_network(sessions_path) -> dict:
    """Build ``{"nodes": [...], "edges": [...]}`` from a ``sessions.csv`` file.

    Node ``count`` is a lecturer's number of distinct course codes (``kode``)
    -- the same definition ``load.py`` uses for ``n_courses`` -- and node
    ``level`` is whichever program level accounts for most of those distinct
    courses (ties broken by ``PROGRAM_LEVELS`` order). Edge ``weight`` is the
    number of distinct courses two lecturers co-teach a section of together
    (not the number of shared session rows, which would inflate weight by a
    class's meeting count). Returns empty lists if the file is missing/empty.
    """
    rows = _read_sessions(sessions_path)
    if not rows:
        return {"nodes": [], "edges": []}

    courses_by_dosen: dict[str, set[str]] = defaultdict(set)
    level_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sections: dict[tuple[str, str], set[str]] = defaultdict(set)

    for row in rows:
        dosen = row["dosen"]
        kode = row.get("kode", "")
        kelas = row.get("kelas", "")
        if kode not in courses_by_dosen[dosen]:
            level = program_level({"rumpun": row.get("rumpun", ""), "kode": kode})
            level_counts[dosen][level] += 1
        courses_by_dosen[dosen].add(kode)
        sections[(kode, kelas)].add(dosen)

    nodes = []
    for dosen, courses in courses_by_dosen.items():
        counts = level_counts[dosen]
        dominant = min(counts, key=lambda lvl: (-counts[lvl], _LEVEL_RANK.get(lvl, len(PROGRAM_LEVELS))))
        nodes.append({"id": dosen, "label": dosen, "count": len(courses), "level": dominant})
    nodes.sort(key=lambda n: n["count"], reverse=True)

    pair_courses: dict[frozenset, set[str]] = defaultdict(set)
    for (kode, _kelas), dosen_set in sections.items():
        if len(dosen_set) < 2:
            continue
        ordered = sorted(dosen_set)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pair_courses[frozenset((ordered[i], ordered[j]))].add(kode)

    edges = []
    for pair, shared in pair_courses.items():
        a, b = sorted(pair)
        edges.append({"source": a, "target": b, "weight": len(shared), "courses": sorted(shared)})
    edges.sort(key=lambda e: e["weight"], reverse=True)

    return {"nodes": nodes, "edges": edges}


def filter_to_lecturers(network: dict, names: list[str]) -> dict:
    """Drop nodes (and their edges) not in ``names``.

    ``sessions.csv`` sees every co-teacher, including ones who were never a
    scrape target and so don't appear in any other exhibit of this report;
    this keeps the network scoped to the same roster the rest of the
    dashboard shows. Matches by ``_fold`` (case/punctuation-insensitive), the
    same identity rule ``load.py`` uses elsewhere.
    """
    keep = {_fold(n) for n in names}
    nodes = [n for n in network["nodes"] if _fold(n["id"]) in keep]
    kept_ids = {n["id"] for n in nodes}
    edges = [
        e for e in network["edges"] if e["source"] in kept_ids and e["target"] in kept_ids
    ]
    return {"nodes": nodes, "edges": edges}
