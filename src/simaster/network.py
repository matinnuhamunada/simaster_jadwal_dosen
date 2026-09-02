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


def build_network(sessions_path, unit: str = "course") -> dict:
    """Build ``{"nodes": [...], "edges": [...]}`` from a ``sessions.csv`` file.

    ``unit`` picks what a node's ``count`` and an edge's ``weight`` are
    measured in:

    - ``"course"`` (default): distinct course codes (``kode``) -- the same
      definition ``load.py`` uses for ``n_courses`` -- so two lecturers who
      co-teach several class sections of the very same course still only
      score 1 on that course.
    - ``"kelas"``: distinct class sections (``kode`` + ``kelas``) -- the same
      granularity ``load.py`` uses for ``n_classes`` -- so co-teaching
      several sections of one course counts each section separately.

    Co-teaching itself is always detected at the class-section level (two
    lecturers must appear on the same ``(kode, kelas)``); ``unit`` only
    changes how that's tallied into node/edge weights.

    Node ``level`` is whichever program level accounts for most of a
    lecturer's counted units (ties broken by ``PROGRAM_LEVELS`` order).
    Returns empty lists if the file is missing/empty.
    """
    if unit not in ("course", "kelas"):
        raise ValueError(f"unknown unit: {unit!r} (expected 'course' or 'kelas')")

    rows = _read_sessions(sessions_path)
    if not rows:
        return {"nodes": [], "edges": []}

    def unit_key(kode, kelas):
        return kode if unit == "course" else (kode, kelas)

    units_by_dosen: dict[str, set] = defaultdict(set)
    level_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sections: dict[tuple[str, str], set[str]] = defaultdict(set)

    for row in rows:
        dosen = row["dosen"]
        kode = row.get("kode", "")
        kelas = row.get("kelas", "")
        key = unit_key(kode, kelas)
        if key not in units_by_dosen[dosen]:
            level = program_level({"rumpun": row.get("rumpun", ""), "kode": kode})
            level_counts[dosen][level] += 1
        units_by_dosen[dosen].add(key)
        sections[(kode, kelas)].add(dosen)

    nodes = []
    for dosen, units in units_by_dosen.items():
        counts = level_counts[dosen]
        dominant = min(counts, key=lambda lvl: (-counts[lvl], _LEVEL_RANK.get(lvl, len(PROGRAM_LEVELS))))
        nodes.append({"id": dosen, "label": dosen, "count": len(units), "level": dominant})
    nodes.sort(key=lambda n: n["count"], reverse=True)

    pair_units: dict[frozenset, set] = defaultdict(set)
    for (kode, kelas), dosen_set in sections.items():
        if len(dosen_set) < 2:
            continue
        ordered = sorted(dosen_set)
        key = unit_key(kode, kelas)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pair_units[frozenset((ordered[i], ordered[j]))].add(key)

    edges = []
    for pair, shared in pair_units.items():
        a, b = sorted(pair)
        if unit == "course":
            items = sorted(shared)
        else:
            items = sorted(f"{kode} ({kelas})" if kelas else kode for kode, kelas in shared)
        edges.append({"source": a, "target": b, "weight": len(shared), "courses": items})
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


def with_scheduled_sks(network: dict, sks_by_dosen: dict) -> dict:
    """Return a copy of ``network`` with each node's ``sks`` set from ``sks_by_dosen``.

    ``sks_by_dosen`` is typically ``{row["dosen"]: row["scheduled_sks"] for
    row in aggregate_loads(...)["lecturers"]}``. Used so the dashboard's
    network diagram can size nodes by each lecturer's actual total teaching
    load rather than by how many courses/class-sections they co-teach; a node
    with no match (shouldn't normally happen after ``filter_to_lecturers``)
    gets ``0.0``.
    """
    nodes = [{**n, "sks": sks_by_dosen.get(n["id"], 0.0)} for n in network["nodes"]]
    return {"nodes": nodes, "edges": network["edges"]}
