import json
import re

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

    def test_empty_result_does_not_crash(self, tmp_path):
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        assert result["lecturers"] == []
        out = render_dashboard(result)
        assert "</html>" in out


class TestWriteDashboard:
    def test_writes_single_html_file(self, tmp_path):
        _write_fixture(tmp_path, "Matin Nuhamunada, S.Si., M.Sc.")
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        out = tmp_path / "out"
        path = write_dashboard(result, out)
        assert path == out / DASHBOARD_FILENAME
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip().lower().startswith("<!doctype html>")

    def test_creates_nested_outdir(self, tmp_path):
        result = aggregate_loads(tmp_path, "20261", 8, 16)
        nested = tmp_path / "a" / "b"
        path = write_dashboard(result, nested)
        assert path.exists()
