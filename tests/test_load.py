import csv
import json

from simaster.load import (
    MEETINGS_PER_SEMESTER,
    aggregate_loads,
    classify,
    compute_lecturer_load,
    write_reports,
)

COURSES_SOLO = [
    {
        "kode": "BISB262101",
        "mata_kuliah": "Bahasa Inggris untuk Biologi",
        "kelas": "IUP",
        "sks": "2.00",
        "jadwal": [
            {"dosen": "Matin Nuhamunada, S.Si., M.Sc."}
            for _ in range(MEETINGS_PER_SEMESTER)
        ],
    }
]


def _entry(dosen):
    return {"dosen": dosen}


class TestClassify:
    def test_bounds(self):
        assert classify(12.0, 12, 16) == "OK"
        assert classify(16.0, 12, 16) == "OK"
        assert classify(11.99, 12, 16) == "UNDERLOADED"
        assert classify(16.01, 12, 16) == "OVERLOADED"


class TestComputeLecturerLoad:
    def test_solo_full_class_gets_full_sks(self):
        load = compute_lecturer_load(COURSES_SOLO, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["total_credit"] == 2.0
        assert load["n_classes"] == 1
        assert load["classes"][0]["own_meetings"] == MEETINGS_PER_SEMESTER

    def test_team_taught_half_share(self):
        courses = [
            {
                "kode": "K1",
                "mata_kuliah": "Genetika",
                "kelas": "A",
                "sks": "3.00",
                "jadwal": [_entry("Matin Nuhamunada, S.Si., M.Sc.")] * 7
                + [_entry("Dr. Luthfi Nurhidayat, S.Si., M.Sc.")] * 7,
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["total_credit"] == 1.5
        assert load["classes"][0]["own_meetings"] == 7

    def test_partial_data_proportional(self):
        courses = [
            {
                "kode": "K2",
                "mata_kuliah": "Botani",
                "kelas": "B",
                "sks": "2.00",
                "jadwal": [_entry("Matin Nuhamunada, S.Si., M.Sc.")] * 5,
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["total_credit"] == round(5 / 14 * 2.0, 2)

    def test_title_variant_matches(self):
        courses = [
            {
                "kode": "K3",
                "mata_kuliah": "MK",
                "kelas": "C",
                "sks": "2.00",
                "jadwal": [_entry("Matin Nuhamunada, S.Si., M.Sc., Ph.D.")] * 7,
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["total_credit"] == 1.0

    def test_empty_courses(self):
        load = compute_lecturer_load([], "Matin")
        assert load == {"total_credit": 0.0, "n_classes": 0, "classes": []}


def _write_fixture(dirpath, stem, dosen, dosen_id, courses):
    path = dirpath / f"jadwal_{stem}_20261.json"
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "semester": "20261",
                    "dosen": dosen,
                    "dosenId": dosen_id,
                },
                "courses": courses,
            }
        ),
        encoding="utf-8",
    )
    return path


class TestAggregateLoads:
    def test_builds_summary_and_warnings(self, tmp_path):
        _write_fixture(tmp_path, "matin", "Matin Nuhamunada, S.Si., M.Sc.", "16764", COURSES_SOLO)
        partial = [
            {
                "kode": "K9",
                "mata_kuliah": "Parsial",
                "kelas": "X",
                "sks": "3.00",
                "jadwal": [_entry("Luthfi Nurhidayat, S.Si., M.Sc.")] * 5,
            }
        ]
        _write_fixture(tmp_path, "luthfi", "Luthfi Nurhidayat, S.Si., M.Sc.", "1", partial)

        result = aggregate_loads(tmp_path, "20261", 12, 16)
        assert len(result["lecturers"]) == 2
        assert result["lecturers"][0]["status"] == "UNDERLOADED"  # sorted desc
        assert any(
            "has 5 meetings" in w and "expected 14" in w for w in result["warnings"]
        )

    def test_dedupe_by_dosen(self, tmp_path):
        _write_fixture(tmp_path, "matin", "Matin Nuhamunada, S.Si., M.Sc.", "16764", COURSES_SOLO)
        _write_fixture(tmp_path, "matin2", "Matin Nuhamunada, S.Si., M.Sc.", "16764", COURSES_SOLO)
        result = aggregate_loads(tmp_path, "20261", 12, 16)
        assert len(result["lecturers"]) == 1
        assert any("duplicate result" in w for w in result["warnings"])

    def test_no_data_for_missing_names(self, tmp_path):
        _write_fixture(
            tmp_path,
            "matin_nuhamunada_s_si_m_sc",
            "Matin Nuhamunada, S.Si., M.Sc.",
            "16764",
            COURSES_SOLO,
        )
        result = aggregate_loads(
            tmp_path, "20261", 12, 16,
            names=["Matin Nuhamunada, S.Si., M.Sc.", "Dr. Jane Doe, S.Si."],
        )
        statuses = {r["status"] for r in result["lecturers"]}
        assert "NO_DATA" in statuses
        no_data = [r for r in result["lecturers"] if r["status"] == "NO_DATA"]
        assert no_data[0]["dosen"] == "Dr. Jane Doe, S.Si."
        present = [r for r in result["lecturers"] if r["status"] != "NO_DATA"]
        assert present[0]["dosen"] == "Matin Nuhamunada, S.Si., M.Sc."
        assert present[0]["status"] == "UNDERLOADED"

    def test_missing_meta_skipped(self, tmp_path):
        p = tmp_path / "jadwal_bad_20261.json"
        p.write_text(json.dumps({"meta": {}, "courses": []}), encoding="utf-8")
        result = aggregate_loads(tmp_path, "20261")
        assert len(result["lecturers"]) == 0
        assert any("missing meta.dosen" in w for w in result["warnings"])


class TestWriteReports:
    def test_outputs_written(self, tmp_path):
        _write_fixture(tmp_path, "matin", "Matin Nuhamunada, S.Si., M.Sc.", "16764", COURSES_SOLO)
        result = aggregate_loads(tmp_path, "20261", 12, 16)
        out = tmp_path / "out"
        paths = write_reports(result, out)
        assert {p.name for p in paths} == {
            "load_summary.csv",
            "load_detail.csv",
            "load_report.md",
        }
        with (out / "load_summary.csv").open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["dosen", "dosenId", "total_sks", "n_classes", "status", "source_file"]
        assert len(rows) == 2
        report = (out / "load_report.md").read_text(encoding="utf-8")
        assert "# Teaching load report" in report
        assert "## Warnings" in report
        assert "Matin Nuhamunada" in report