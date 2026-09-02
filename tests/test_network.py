import csv

import pytest

from simaster.network import build_network, filter_to_lecturers, with_scheduled_sks

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


def _row(kode, kelas, dosen, tanggal="2026-09-02", jam="09:00-09:50", rumpun="[PRODI] S1 BIOLOGI"):
    return [kode, "MK", kelas, "2.00", "30", rumpun, "Senin", tanggal, jam, "Ruang 1", dosen]


def _write_sessions(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(rows)


def _by_id(nodes):
    return {n["id"]: n for n in nodes}


def _edge_between(edges, a, b):
    for e in edges:
        if {e["source"], e["target"]} == {a, b}:
            return e
    return None


class TestBuildNetwork:
    def test_missing_file_returns_empty(self, tmp_path):
        result = build_network(tmp_path / "sessions.csv")
        assert result == {"nodes": [], "edges": []}

    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "sessions.csv"
        _write_sessions(path, [])
        assert build_network(path) == {"nodes": [], "edges": []}

    def test_node_count_is_distinct_courses(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice"),
            _row("A101", "REG", "Alice", tanggal="2026-09-09"),  # same course again
            _row("B202", "REG", "Alice"),
        ]
        _write_sessions(path, rows)
        nodes = _by_id(build_network(path)["nodes"])
        assert nodes["Alice"]["count"] == 2

    def test_edge_weight_is_distinct_shared_courses_not_session_count(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [_row("A101", "REG", "Alice", jam=f"{h:02d}:00-{h:02d}:50") for h in range(8, 22)]
        rows += [_row("A101", "REG", "Bob", jam=f"{h:02d}:00-{h:02d}:50") for h in range(8, 22)]
        assert len(rows) == 28  # 14 meetings each, same (kode, kelas)
        _write_sessions(path, rows)
        edges = build_network(path)["edges"]
        edge = _edge_between(edges, "Alice", "Bob")
        assert edge is not None
        assert edge["weight"] == 1
        assert edge["courses"] == ["A101"]

    def test_edge_weight_counts_multiple_shared_courses(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice"),
            _row("A101", "REG", "Bob"),
            _row("B202", "REG", "Alice"),
            _row("B202", "REG", "Bob"),
        ]
        _write_sessions(path, rows)
        edges = build_network(path)["edges"]
        edge = _edge_between(edges, "Alice", "Bob")
        assert edge["weight"] == 2
        assert edge["courses"] == ["A101", "B202"]

    def test_three_way_class_produces_all_pairs(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice"),
            _row("A101", "REG", "Bob"),
            _row("A101", "REG", "Carol"),
        ]
        _write_sessions(path, rows)
        edges = build_network(path)["edges"]
        assert len(edges) == 3
        for a, b in [("Alice", "Bob"), ("Alice", "Carol"), ("Bob", "Carol")]:
            edge = _edge_between(edges, a, b)
            assert edge is not None
            assert edge["courses"] == ["A101"]

    def test_solo_taught_class_produces_no_edge(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [_row("A101", "REG", "Alice")]
        _write_sessions(path, rows)
        result = build_network(path)
        assert result["edges"] == []
        assert _by_id(result["nodes"])["Alice"]["count"] == 1

    def test_node_level_picks_dominant_by_distinct_course_count(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice", rumpun="[PRODI] S1 BIOLOGI"),
            _row("B202", "REG", "Alice", rumpun="[PRODI] S1 BIOLOGI"),
            _row("C303", "REG", "Alice", rumpun="[PRODI] MAGISTER BIOLOGI"),
        ]
        _write_sessions(path, rows)
        node = _by_id(build_network(path)["nodes"])["Alice"]
        assert node["level"] == "S1"

    def test_node_level_ties_broken_by_program_level_order(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice", rumpun="[PRODI] MAGISTER BIOLOGI"),
            _row("B202", "REG", "Alice", rumpun="[PRODI] S1 BIOLOGI"),
        ]
        _write_sessions(path, rows)
        node = _by_id(build_network(path)["nodes"])["Alice"]
        assert node["level"] == "S1"


class TestBuildNetworkKelasUnit:
    def test_node_count_is_distinct_class_sections(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "A", "Alice"),
            _row("A101", "B", "Alice"),  # same course, different kelas
            _row("A101", "A", "Alice", tanggal="2026-09-09"),  # same section again
        ]
        _write_sessions(path, rows)
        nodes = _by_id(build_network(path, unit="kelas")["nodes"])
        assert nodes["Alice"]["count"] == 2

    def test_edge_weight_counts_shared_sections_not_courses(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "A", "Alice"),
            _row("A101", "A", "Bob"),
            _row("A101", "B", "Alice"),
            _row("A101", "B", "Bob"),
        ]
        _write_sessions(path, rows)
        course_edge = _edge_between(build_network(path, unit="course")["edges"], "Alice", "Bob")
        kelas_edge = _edge_between(build_network(path, unit="kelas")["edges"], "Alice", "Bob")
        # Same course (A101) both times -> 1 on the course-level network...
        assert course_edge["weight"] == 1
        # ...but two distinct sections (A101/A, A101/B) -> 2 on the kelas one.
        assert kelas_edge["weight"] == 2
        assert kelas_edge["courses"] == ["A101 (A)", "A101 (B)"]

    def test_invalid_unit_raises(self, tmp_path):
        path = tmp_path / "sessions.csv"
        _write_sessions(path, [_row("A101", "A", "Alice")])
        with pytest.raises(ValueError):
            build_network(path, unit="bogus")


class TestFilterToLecturers:
    def _network(self, tmp_path):
        path = tmp_path / "sessions.csv"
        rows = [
            _row("A101", "REG", "Alice"),
            _row("A101", "REG", "Bob"),
            _row("A101", "REG", "Carol"),
        ]
        _write_sessions(path, rows)
        return build_network(path)

    def test_drops_unlisted_nodes(self, tmp_path):
        network = self._network(tmp_path)
        filtered = filter_to_lecturers(network, ["Alice", "Bob"])
        assert {n["id"] for n in filtered["nodes"]} == {"Alice", "Bob"}

    def test_drops_edges_touching_an_unlisted_node(self, tmp_path):
        network = self._network(tmp_path)
        filtered = filter_to_lecturers(network, ["Alice", "Bob"])
        # Carol was dropped, so her edges to Alice and Bob must go too.
        assert len(filtered["edges"]) == 1
        edge = filtered["edges"][0]
        assert {edge["source"], edge["target"]} == {"Alice", "Bob"}

    def test_keeps_edge_when_both_endpoints_listed(self, tmp_path):
        network = self._network(tmp_path)
        filtered = filter_to_lecturers(network, ["Alice", "Bob", "Carol"])
        assert len(filtered["nodes"]) == 3
        assert len(filtered["edges"]) == 3

    def test_matches_by_fold(self, tmp_path):
        network = self._network(tmp_path)
        filtered = filter_to_lecturers(network, ["  alice  ", "BOB"])
        assert {n["id"] for n in filtered["nodes"]} == {"Alice", "Bob"}


class TestWithScheduledSks:
    def test_attaches_sks_by_dosen(self):
        network = {
            "nodes": [
                {"id": "Alice", "label": "Alice", "count": 3, "level": "S1"},
                {"id": "Bob", "label": "Bob", "count": 2, "level": "S2"},
            ],
            "edges": [],
        }
        out = with_scheduled_sks(network, {"Alice": 12.5, "Bob": 4.0})
        assert _by_id(out["nodes"])["Alice"]["sks"] == 12.5
        assert _by_id(out["nodes"])["Bob"]["sks"] == 4.0

    def test_missing_lecturer_defaults_to_zero(self):
        network = {"nodes": [{"id": "Carol", "label": "Carol", "count": 1, "level": "S1"}], "edges": []}
        out = with_scheduled_sks(network, {})
        assert _by_id(out["nodes"])["Carol"]["sks"] == 0.0

    def test_does_not_mutate_input(self):
        network = {"nodes": [{"id": "Alice", "label": "Alice", "count": 1, "level": "S1"}], "edges": []}
        with_scheduled_sks(network, {"Alice": 5.0})
        assert "sks" not in network["nodes"][0]

    def test_edges_untouched(self):
        network = {
            "nodes": [
                {"id": "Alice", "label": "Alice", "count": 1, "level": "S1"},
                {"id": "Bob", "label": "Bob", "count": 1, "level": "S1"},
            ],
            "edges": [{"source": "Alice", "target": "Bob", "weight": 1, "courses": ["A101"]}],
        }
        out = with_scheduled_sks(network, {"Alice": 1.0, "Bob": 1.0})
        assert out["edges"] == network["edges"]
