import csv
import json

from simaster.output import write_outputs

META = {
    "semester": "20261",
    "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
    "dosenId": "16764",
    "generated_at": "2026-08-19T08:00:00",
    "total_courses": 1,
    "total_entries": 1,
    "reported_total": 1,
}

COURSES = [
    {
        "no": "1",
        "rumpun": "[PRODI] S1 BIOLOGI",
        "kode": "BISB262101",
        "mata_kuliah": "Bahasa Inggris untuk Biologi",
        "kelas": "IUP",
        "sks": "2.00",
        "jml_mhs": "",
        "jadwal": [
            {
                "hari": "Jumat",
                "tanggal": "2026-08-21",
                "jam": "07:15-08:55",
                "ruang": "Ruang 1",
                "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
            }
        ],
    }
]


def test_writes_json_and_csv(tmp_path):
    json_path, csv_path = write_outputs(
        "Matin Nuhamunada, S.Si., M.Sc.", "20261", META, COURSES, tmp_path
    )
    assert json_path == tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.json"
    assert csv_path == tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.csv"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["meta"]["total_courses"] == 1
    assert data["courses"][0]["kode"] == "BISB262101"

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
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
    assert rows[1][:3] == ["BISB262101", "Bahasa Inggris untuk Biologi", "IUP"]


def test_creates_outdir(tmp_path):
    out = tmp_path / "nested" / "dir"
    json_path, csv_path = write_outputs("Matin Nuhamunada", "20261", META, COURSES, out)
    assert json_path.exists() and csv_path.exists()