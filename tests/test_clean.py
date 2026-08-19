import csv
import json

from simaster.clean import (
    aggregate_sessions,
    clean_all,
    clean_lecturer_file,
    dedupe_sessions,
    is_s3,
)

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


def _csv_row(kode, kelas, tanggal, jam, dosen, rumpun="[PRODI] S1 BIOLOGI", sks="2.00"):
    return [kode, "MK", kelas, sks, "30", rumpun, "Senin", tanggal, jam, "Ruang 1", dosen]


def _write_raw(dirpath, stem, dosen, courses, rows):
    (dirpath / f"jadwal_{stem}_20261.json").write_text(
        json.dumps(
            {
                "meta": {"semester": "20261", "dosen": dosen, "dosenId": "1"},
                "courses": courses,
            }
        ),
        encoding="utf-8",
    )
    with (dirpath / f"jadwal_{stem}_20261.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(rows)


def _entry(tanggal, jam, dosen):
    return {"hari": "Senin", "tanggal": tanggal, "jam": jam, "ruang": "Ruang 1", "dosen": dosen}


class TestAggregateDedupe:
    def test_concatenates_and_dedupes(self, tmp_path):
        shared = _csv_row("K1", "A", "2026-08-21", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc.")
        _write_raw(tmp_path, "matin", "Matin Nuhamunada, S.Si., M.Sc.", [], [shared])
        other = _csv_row("K1", "A", "2026-08-21", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc.")
        _write_raw(tmp_path, "luthfi", "Luthfi Nurhidayat, S.Si., M.Sc.", [], [other])

        header, rows = aggregate_sessions(tmp_path, "20261")
        assert len(rows) == 2  # same session listed in both co-teachers' files
        unique = dedupe_sessions(rows)
        assert len(unique) == 1  # redundant session deleted

    def test_header_from_first_file(self, tmp_path):
        _write_raw(tmp_path, "matin", "Matin Nuhamunada, S.Si., M.Sc.", [], [])
        header, _ = aggregate_sessions(tmp_path, "20261")
        assert header == CSV_HEADER


class TestIsS3:
    def test_by_rumpun_and_kode(self):
        assert is_s3({"rumpun": "[PRODI] DOKTOR BIOLOGI", "kode": "X"}) is True
        assert is_s3({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BIDB203201"}) is True
        assert is_s3({"rumpun": "[PRODI] S1 BIOLOGI", "kode": "BISB262101"}) is False


class TestCleanLecturerFile:
    def test_own_entries_and_estimates(self):
        counts = {("BISB1", "A"): 14, ("BISB2", "B"): 0, ("BIDB1", "C"): 0}
        courses = [
            {
                "kode": "BISB1",
                "mata_kuliah": "Bahasa Inggris",
                "kelas": "A",
                "sks": "2.00",
                "rumpun": "[PRODI] S1 BIOLOGI",
                "jadwal": [_entry("2026-08-21", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc.")]
                + [_entry("2026-08-21", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc.")]  # dupe
                + [_entry("2026-08-28", "07:00-08:00", "Luthfi Nurhidayat, S.Si., M.Sc.")] * 7
                + [
                    _entry(f"2026-09-0{i}", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc.")
                    for i in range(4, 10)
                ],
            },
            {
                "kode": "BISB2",
                "mata_kuliah": "Botani",
                "kelas": "B",
                "sks": "3.00",
                "rumpun": "[PRODI] S1 BIOLOGI",
                "jadwal": [],
            },
            {
                "kode": "BIDB1",
                "mata_kuliah": "Disertasi",
                "kelas": "C",
                "sks": "4.00",
                "rumpun": "[PRODI] DOKTOR BIOLOGI",
                "jadwal": [],
            },
        ]
        meta = {"semester": "20261", "dosen": "Matin Nuhamunada, S.Si., M.Sc.", "dosenId": "1"}
        clean = clean_lecturer_file(meta, courses, counts)

        c0 = clean["courses"][0]
        assert c0["class_meetings"] == 14
        assert c0["own_meetings"] == 7  # deduped: 6 + 1 (dupe collapsed)
        assert len(c0["jadwal"]) == 7
        assert all(e["dosen"] == "Matin Nuhamunada, S.Si., M.Sc." for e in c0["jadwal"])

        m = clean["meta"]
        assert m["own_entries"] == 7
        # BISB1: 7/14*2 = 1.0 ; BISB2 unscheduled: 3.0 ; BIDB1 unscheduled: 4.0
        assert m["est_sks"] == 8.0
        assert m["est_sks_no_s3"] == 4.0  # excludes BIDB1
        assert m["n_unscheduled"] == 2
        assert m["n_s3"] == 1


class TestCleanAll:
    def test_writes_sessions_and_clean_files(self, tmp_path):
        matin_rows = [
            _csv_row("K1", "A", "2026-08-21", "07:00-08:00", "Matin Nuhamunada, S.Si., M.Sc."),
            _csv_row("K1", "A", "2026-08-28", "07:00-08:00", "Luthfi Nurhidayat, S.Si., M.Sc."),
        ]
        courses = [
            {
                "kode": "K1",
                "mata_kuliah": "MK",
                "kelas": "A",
                "sks": "2.00",
                "rumpun": "[PRODI] S1 BIOLOGI",
                "jadwal": [
                    {"hari": "Senin", "tanggal": "2026-08-21", "jam": "07:00-08:00", "ruang": "Ruang 1", "dosen": "Matin Nuhamunada, S.Si., M.Sc."},
                    {"hari": "Senin", "tanggal": "2026-08-28", "jam": "07:00-08:00", "ruang": "Ruang 1", "dosen": "Luthfi Nurhidayat, S.Si., M.Sc."},
                ],
            }
        ]
        _write_raw(tmp_path, "matin_nuhamunada_s_si_m_sc", "Matin Nuhamunada, S.Si., M.Sc.", courses, matin_rows)

        out = tmp_path / "clean"
        result = clean_all(
            tmp_path, "20261", ["Matin Nuhamunada, S.Si., M.Sc.", "Nobody Here"], outdir=out
        )
        assert result["n_raw_sessions"] == 2
        assert result["n_sessions"] == 2
        assert result["n_written"] == 1  # Nobody Here has no raw file

        with (out / "sessions.csv").open(newline="", encoding="utf-8-sig") as f:
            sess = list(csv.reader(f))
        assert sess[0] == CSV_HEADER
        assert len(sess) == 3  # header + 2 unique sessions

        clean_path = out / "jadwal_matin_nuhamunada_s_si_m_sc_20261.json"
        assert clean_path.exists()
        data = json.loads(clean_path.read_text(encoding="utf-8"))
        assert data["meta"]["own_entries"] == 1  # only Matin's own session
        assert len(data["courses"][0]["jadwal"]) == 1
        assert not (out / "jadwal_nobody_here_20261.json").exists()