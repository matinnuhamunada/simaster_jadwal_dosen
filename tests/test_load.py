import csv
import json

from simaster.load import (
    MEETINGS_PER_SEMESTER,
    SUMMARY_HEADER,
    aggregate_loads,
    classify,
    compute_lecturer_load,
    is_s3,
    program_level,
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
        assert classify(5.99, warn=6, ok_min=8, ok_high=12, max_sks=16) == "WARNING"
        assert classify(6.0, warn=6, ok_min=8, ok_high=12, max_sks=16) == "UNDERLOADED"
        assert classify(7.99, warn=6, ok_min=8, ok_high=12, max_sks=16) == "UNDERLOADED"
        assert classify(8.0, warn=6, ok_min=8, ok_high=12, max_sks=16) == "OK"
        assert classify(12.0, warn=6, ok_min=8, ok_high=12, max_sks=16) == "OK"
        assert classify(12.01, warn=6, ok_min=8, ok_high=12, max_sks=16) == "ABOVE"
        assert classify(16.0, warn=6, ok_min=8, ok_high=12, max_sks=16) == "ABOVE"
        assert classify(16.01, warn=6, ok_min=8, ok_high=12, max_sks=16) == "OVERLOADED"

    def test_defaults(self):
        assert classify(5.0) == "WARNING"
        assert classify(9.0) == "OK"
        assert classify(14.0) == "ABOVE"
        assert classify(17.0) == "OVERLOADED"


class TestComputeLecturerLoad:
    def test_solo_full_class_gets_full_sks(self):
        load = compute_lecturer_load(COURSES_SOLO, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["total_credit"] == 2.0
        assert load["n_classes"] == 1
        assert load["classes"][0]["own_meetings"] == MEETINGS_PER_SEMESTER

    def test_classes_include_rumpun_and_level(self):
        courses = [
            {
                "kode": "BIMB101",
                "mata_kuliah": "Biologi Molekuler Lanjut",
                "kelas": "A",
                "sks": "2.00",
                "rumpun": "[PRODI] MAGISTER BIOLOGI",
                "jadwal": [_entry("Matin Nuhamunada, S.Si., M.Sc.")] * MEETINGS_PER_SEMESTER,
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["classes"][0]["rumpun"] == "[PRODI] MAGISTER BIOLOGI"
        assert load["classes"][0]["level"] == "S2"

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
        assert load == {
            "total_credit": 0.0,
            "est_sks": 0.0,
            "est_sks_no_s3": 0.0,
            "n_unscheduled": 0,
            "n_s3": 0,
            "n_classes": 0,
            "n_courses": 0,
            "classes": [],
        }

    def test_unscheduled_class_assumes_full_sks(self):
        courses = [
            {
                "kode": "K4",
                "mata_kuliah": "Disertasi",
                "kelas": "D",
                "sks": "4.00",
                "jadwal": [],
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["est_sks"] == 4.0
        assert load["total_credit"] == 0.0
        assert load["n_unscheduled"] == 1
        assert load["classes"][0]["est_credit"] == 4.0

    def test_s3_excluded_from_no_s3_estimate(self):
        courses = [
            {
                "kode": "BIDB267103",
                "mata_kuliah": "Pengembangan Proposal",
                "kelas": "A",
                "sks": "2.00",
                "rumpun": "[PRODI] DOKTOR BIOLOGI",
                "jadwal": [],
            },
            {
                "kode": "BISB262101",
                "mata_kuliah": "Bahasa Inggris",
                "kelas": "IUP",
                "sks": "2.00",
                "rumpun": "[PRODI] S1 BIOLOGI",
                "jadwal": [],
            },
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["est_sks"] == 4.0
        assert load["est_sks_no_s3"] == 2.0
        assert load["n_s3"] == 1
        assert load["classes"][0]["is_s3"] is True

    def test_class_meetings_read_from_field(self):
        courses = [
            {
                "kode": "K5",
                "mata_kuliah": "MK",
                "kelas": "E",
                "sks": "3.00",
                "class_meetings": 14,
                "jadwal": [_entry("Matin Nuhamunada, S.Si., M.Sc.")] * 7,
            }
        ]
        load = compute_lecturer_load(courses, "Matin Nuhamunada, S.Si., M.Sc.")
        assert load["classes"][0]["class_meetings"] == 14
        assert load["total_credit"] == 1.5


class TestIsS3:
    def test_by_rumpun(self):
        assert is_s3({"rumpun": "[PRODI] DOKTOR BIOLOGI", "kode": "X"}) is True

    def test_by_kode_prefix(self):
        assert is_s3({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BIDB203201"}) is True

    def test_not_s3(self):
        assert is_s3({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BISB262101"}) is False


class TestProgramLevel:
    def test_doktor_is_s3(self):
        assert program_level({"rumpun": "[PRODI] DOKTOR BIOLOGI", "kode": "BIDB203201"}) == "S3"

    def test_magister_is_s2(self):
        assert program_level({"rumpun": "[PRODI] MAGISTER BIOLOGI", "kode": "BIMB101"}) == "S2"
        assert program_level({"rumpun": "Magister Manajemen", "kode": "MAN101"}) == "S2"

    def test_s1_prefixed_rumpun(self):
        assert program_level({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BISB262101"}) == "S1"
        assert program_level({"rumpun": "[GABUNG] S1 GEOGRAFI", "kode": "GEGL101"}) == "S1"

    def test_profesi(self):
        assert (
            program_level(
                {"rumpun": "[PRODI] Profesi Kurator Keanekaragaman Hayati", "kode": "BIPO101"}
            )
            == "PROFESI"
        )

    def test_unrecognized_is_other(self):
        assert program_level({"rumpun": "Something Else", "kode": "X"}) == "OTHER"
        assert program_level({"rumpun": "", "kode": "X"}) == "OTHER"

    def test_kode_prefix_forces_s3_over_rumpun_text(self):
        assert program_level({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BIDB203201"}) == "S3"


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
        assert result["lecturers"][0]["status"] == "WARNING"  # total 2.0, sorted desc
        assert any(
            "has 5 meetings" in w and "expected 8-14" in w for w in result["warnings"]
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
        assert present[0]["status"] == "WARNING"  # total 2.0 (< 6)

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
        assert rows[0] == SUMMARY_HEADER
        assert len(rows) == 2
        report = (out / "load_report.md").read_text(encoding="utf-8")
        assert "# Teaching load report" in report
        assert "## Warnings" in report
        assert "## By program level" in report
        assert "Matin Nuhamunada" in report

        with (out / "load_detail.csv").open(newline="", encoding="utf-8-sig") as f:
            detail_rows = list(csv.reader(f))
        assert "rumpun" in detail_rows[0]
        assert "level" in detail_rows[0]