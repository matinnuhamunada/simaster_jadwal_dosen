import csv

from simaster.network import build_network, filter_to_lecturers

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
