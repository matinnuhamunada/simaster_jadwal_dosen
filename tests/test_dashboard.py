import json
import re

import pytest

from simaster.dashboard import DASHBOARD_FILENAME, render_dashboard, write_dashboard
from simaster.load import MEETINGS_PER_SEMESTER, aggregate_loads

COURSE = {
    "kode": "BISB262101",
    "mata_kuliah": "Bahasa Inggris untuk Biologi",
    "kelas": "IUP",
    "sks": "2.00",
    "jadwal": [{"dosen": "Matin Nuhamunada, S.Si., M.Sc."}] * MEETINGS_PER_SEMESTER,
}


def _write_fixture(tmp_path, dosen, kode="jadwal_lecturer", courses=None):
    (tmp_path / f"{kode}_20261.json").write_text(
        json.dumps(
            {
                "meta": {"semester": "20261", "dosen": dosen, "dosenId": "1"},
                "courses": courses if courses is not None else [COURSE],
            }
        ),
        encoding="utf-8",
    )


class TestRenderDashboard:
    def test_basic_structure(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert out.strip().lower().startswith("<!doctype html>")
        assert "</html>" in out
        assert "<script>" in out

    def test_escapes_lecturer_name_outside_script(self, tmp_path):
        # Table data is embedded as JSON inside <script> and rendered client-side
        # via textContent (safe: raw text there isn't parsed as HTML tags), so
        # only the static, hand-built sections need html.escape().
        dosen = 'A & B <Test> "Quote"'
        _write_fixture(tmp_path, dosen)
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        without_scripts = re.sub(r"<script>.*?</script>", "", out, flags=re.S)
        assert "<Test>" not in without_scripts
        assert json.dumps(dosen) in out

    def test_escapes_warning_text(self, tmp_path):
        dosen = 'A & B <Test> "Quote"'
        courses = [{**COURSE, "jadwal": COURSE["jadwal"][:5]}]
        _write_fixture(tmp_path, dosen, courses=courses)
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        assert result["warnings"]
        out = render_dashboard(result)
        without_scripts = re.sub(r"<script>.*?</script>", "", out, flags=re.S)
        assert "<Test>" not in without_scripts
        assert "&lt;Test&gt;" in without_scripts

    def test_status_labels_present(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        for status in ["OVERLOADED", "ABOVE", "OK", "UNDERLOADED", "WARNING", "NO_DATA"]:
            assert status in out

    def test_warnings_rendered(self, tmp_path):
        courses = [{**COURSE, "jadwal": COURSE["jadwal"][:5]}]
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.", courses=courses)
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        assert result["warnings"]
        out = render_dashboard(result)
        assert "Warnings (1)" in out

    def test_program_level_breakdown_present(self, tmp_path):
        courses = [
            {**COURSE, "kode": "BISB1", "rumpun": "[PRODI] S1 BIOLOGI"},
            {**COURSE, "kode": "BIMB1", "rumpun": "[PRODI] MAGISTER BIOLOGI"},
            {**COURSE, "kode": "BIDB1", "rumpun": "[PRODI] DOKTOR BIOLOGI"},
        ]
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.", courses=courses)
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert "By program level" in out
        for level in ["S1", "S2", "S3", "PROFESI", "OTHER"]:
            assert f'level-{level}"' in out
        # rumpun/level columns present in the per-class table headers
        assert "Rumpun/Prodi" in out
        assert '<th data-key="level">Level</th>' in out
        assert json.dumps("[PRODI] MAGISTER BIOLOGI") in out

    def test_per_class_table_has_no_s3_column(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert '<th data-key="is_s3"' not in out
        assert ">S3</th>" not in out

    def test_empty_result_does_not_crash(self, tmp_path):
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        assert result["lecturers"] == []
        out = render_dashboard(result)
        assert "</html>" in out

    def test_methodology_present_with_interpolated_bands(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16, warn=6)
        out = render_dashboard(result)
        assert "Methodology" in out
        assert "Scheduled SKS" in out
        # band cutoffs (warn=6, ok_min=8, ok_high=12, max_sks=16) interpolated as prose
        assert "below 6" in out
        assert "12" in out and "16" in out

    def test_section_captions_present(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert "Click a name to filter" in out
        assert "Click a level tile to filter" in out
        assert "co-taught class" in out
        assert "make-up class" in out

    def test_captions_are_escaped_static_text(self, tmp_path):
        # Captions are developer-authored constants (no user data), but should
        # still render as plain text outside <script>, same as other static copy.
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        without_scripts = re.sub(r"<script>.*?</script>", "", out, flags=re.S)
        assert "Ranked by Scheduled SKS" in without_scripts

    def test_level_bars_present(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert 'id="level-total-bar"' in out
        assert 'id="level-bars"' in out
        assert "By lecturer" in out
        assert "LEVEL_SKS_FIELDS" in out
        assert json.dumps("sks_s1") in out

    def test_level_card_totals_match_lecturer_field_sums(self, tmp_path):
        # _level_cards() sums own_credit over result["classes"]; the new bars
        # sum sks_s1..sks_profesi over result["lecturers"] client-side. These
        # are two different computations over the same underlying scheduled
        # sessions and must agree, or the total bar and the cards would show
        # different numbers for the same data.
        courses = [
            {**COURSE, "kode": "BISB1", "rumpun": "[PRODI] S1 BIOLOGI"},
            {**COURSE, "kode": "BIMB1", "rumpun": "[PRODI] MAGISTER BIOLOGI"},
            {**COURSE, "kode": "BIDB1", "rumpun": "[PRODI] DOKTOR BIOLOGI"},
        ]
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.", courses=courses)
        result = aggregate_loads(tmp_path, "20261", 8, 16)

        card_totals = {level: 0.0 for level in ["S1", "S2", "S3", "PROFESI", "OTHER"]}
        for row in result["classes"]:
            card_totals[row["level"]] += row["own_credit"]

        field_totals = {"S1": 0.0, "S2": 0.0, "S3": 0.0, "PROFESI": 0.0}
        for row in result["lecturers"]:
            field_totals["S1"] += row["sks_s1"]
            field_totals["S2"] += row["sks_s2"]
            field_totals["S3"] += row["sks_s3"]
            field_totals["PROFESI"] += row["sks_profesi"]

        for level, total in field_totals.items():
            assert card_totals[level] == pytest.approx(total, abs=0.01)

    def test_network_omitted_without_network_arg(self, tmp_path):
        # Backward compatibility: existing render_dashboard(result) callers
        # (no network kwarg) must keep working and simply omit the exhibit.
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert "Shared-course network" not in out
        assert 'id="network-matrix"' not in out

    def test_network_omitted_for_empty_network(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result, network={"nodes": [], "edges": []})
        assert "Shared-course network" not in out

    def test_network_exhibit_rendered_when_present(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        network = {
            "nodes": [
                {"id": "Alice", "label": "Alice", "count": 3, "level": "S1"},
                {"id": "Bob", "label": "Bob", "count": 2, "level": "S2"},
            ],
            "edges": [{"source": "Alice", "target": "Bob", "weight": 2, "courses": ["A101", "B202"]}],
        }
        out = render_dashboard(result, network=network)
        assert "Shared-course network" in out
        assert 'id="network-matrix"' in out
        assert "const NETWORK = " in out
        assert json.dumps("Alice") in out
        # Tooltip content is built via innerHTML from JSON-embedded names, so
        # it must escape before interpolating (a lecturer/course name could
        # contain HTML metacharacters).
        assert "function escapeHtml(" in out

    def test_class_network_omitted_without_arg(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert "Shared-class network" not in out
        assert 'id="network-kelas-matrix"' not in out

    def test_class_network_exhibit_rendered_when_present(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        class_network = {
            "nodes": [
                {"id": "Alice", "label": "Alice", "count": 3, "level": "S1"},
                {"id": "Bob", "label": "Bob", "count": 2, "level": "S2"},
            ],
            "edges": [{"source": "Alice", "target": "Bob", "weight": 2, "courses": ["A101 (A)", "A101 (B)"]}],
        }
        out = render_dashboard(result, class_network=class_network)
        assert "Shared-class network" in out
        assert 'id="network-kelas-matrix"' in out
        assert "const NETWORK_KELAS = " in out

    def test_both_networks_get_distinct_exhibit_numbers(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        network = {
            "nodes": [{"id": "Alice", "label": "Alice", "count": 1, "level": "S1"}],
            "edges": [],
        }
        out = render_dashboard(result, network=network, class_network=network)
        assert "Exhibit 4</span> Shared-course network" in out
        assert "Exhibit 5</span> Shared-class network" in out
        assert "Exhibit 6</span> Warnings" in out

    def test_calendar_link_uses_default_dir(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert json.dumps("assets/calendar/jadwal_matin_nuhamunada_s_si_m_sc_20261.ics") in out

    def test_calendar_link_respects_custom_dir(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result, calendar_dir="ics")
        assert json.dumps("ics/jadwal_matin_nuhamunada_s_si_m_sc_20261.ics") in out

    def test_calendar_column_omitted_when_dir_is_falsy(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result, calendar_dir="")
        assert '"Calendar"' not in out
        lecturer_cols_line = next(l for l in out.splitlines() if l.startswith("const LECTURER_COLUMNS"))
        assert "ics" not in json.loads(lecturer_cols_line.split("=", 1)[1].rstrip(";").strip())

    def test_calendar_link_rendered_as_a_button(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = render_dashboard(result)
        assert 'a.className = "ics-btn"' in out
        assert ".ics-btn {" in out

    def test_diagram_rendered_before_matrix(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        network = {
            "nodes": [{"id": "Alice", "label": "Alice", "count": 1, "level": "S1", "sks": 4.0}],
            "edges": [],
        }
        out = render_dashboard(result, network=network)
        assert out.index(">Diagram</h3>") < out.index(">Matrix</h3>")

    def test_network_node_sized_by_scheduled_sks(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        network = {
            "nodes": [
                {"id": "Alice", "label": "Alice", "count": 1, "level": "S1", "sks": 12.5},
                {"id": "Bob", "label": "Bob", "count": 1, "level": "S2", "sks": 2.0},
            ],
            "edges": [{"source": "Alice", "target": "Bob", "weight": 1, "courses": ["A101"]}],
        }
        out = render_dashboard(result, network=network)
        assert json.dumps(12.5) in out
        assert "node.sks" in out
        assert "scheduled SKS" in out


class TestWriteDashboard:
    def test_writes_single_html_file(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = tmp_path / "out"
        path = write_dashboard(result, out)
        assert path == out / DASHBOARD_FILENAME
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip().lower().startswith("<!doctype html>")

    def test_forwards_network_to_render(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        network = {
            "nodes": [{"id": "Alice", "label": "Alice", "count": 1, "level": "S1"}],
            "edges": [],
        }
        out = tmp_path / "out"
        path = write_dashboard(result, out, network=network)
        assert "Shared-course network" in path.read_text(encoding="utf-8")

    def test_creates_nested_outdir(self, tmp_path):
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        nested = tmp_path / "a" / "b"
        path = write_dashboard(result, nested)
        assert path.exists()

    def test_respects_custom_filename(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = tmp_path / "out"
        path = write_dashboard(result, out, filename="report.html")
        assert path == out / "report.html"
        assert path.exists()

    def test_forwards_class_network_to_render(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        class_network = {
            "nodes": [{"id": "Alice", "label": "Alice", "count": 1, "level": "S1"}],
            "edges": [],
        }
        out = tmp_path / "out"
        path = write_dashboard(result, out, class_network=class_network)
        assert "Shared-class network" in path.read_text(encoding="utf-8")
