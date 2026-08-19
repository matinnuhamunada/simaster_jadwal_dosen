import pytest

from simaster.parse import (
    best_match,
    canonical_name,
    current_offset,
    find_dosen,
    normalize_date,
    parse_schedule_waktu,
    parse_table_rows,
    slugify,
    term_candidates,
)


class TestNormalizeDate:
    def test_pads_and_orders(self):
        assert normalize_date("21", "08", "2026") == "2026-08-21"

    def test_single_digit_padding(self):
        assert normalize_date("3", "1", "2026") == "2026-01-03"


class TestParseScheduleWaktu:
    def test_typical_value(self):
        assert parse_schedule_waktu("Jumat 21-08-2026 07:15-08:55") == {
            "hari": "Jumat",
            "tanggal": "2026-08-21",
            "jam": "07:15-08:55",
        }

    def test_leading_space(self):
        assert parse_schedule_waktu(" Senin 02-09-2026 10:00-11:40 ")["hari"] == "Senin"

    def test_unparseable_returns_raw_fallback(self):
        assert parse_schedule_waktu("Ruang Sidang") == {
            "hari": "",
            "tanggal": "",
            "jam": "Ruang Sidang",
        }


class TestParseTableRows:
    def test_course_and_schedule_rows(self):
        rows = [
            ["1", "[PRODI] S1 BIOLOGI", "header", "BISB262101", "Bahasa Inggris", "IUP", "2.00", ""],
            ["1", "Jumat 21-08-2026 07:15-08:55", "Ruang 1", "Luthfi Nurhidayat, S.Si., M.Sc."],
            ["2", "Senin 02-09-2026 10:00-11:40", "Ruang 2", "Matin Nuhamunada"],
            ["2", "[PRODI] S1 BIOLOGI", "header", "BISB262102", "Genetika", "A", "3.00", "40"],
        ]
        courses = parse_table_rows(rows)
        assert len(courses) == 2
        assert courses[0]["kode"] == "BISB262101"
        assert courses[0]["mata_kuliah"] == "Bahasa Inggris"
        assert len(courses[0]["jadwal"]) == 2
        assert courses[0]["jadwal"][0]["ruang"] == "Ruang 1"
        assert courses[1]["jadwal"] == []

    def test_short_course_row_ignored(self):
        rows = [["1", "x"], ["1", "y"]]
        assert parse_table_rows(rows) == []

    def test_schedule_row_without_current_course_ignored(self):
        rows = [["1", "Jumat 21-08-2026 07:15-08:55", "Ruang 1", "Dosen"]]
        assert parse_table_rows(rows) == []


class TestCurrentOffset:
    def test_plain_url(self):
        assert (
            current_offset(
                "https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen/view_jadwal_mengajar"
            )
            == 0
        )

    def test_paginated(self):
        assert (
            current_offset(
                "https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen/view_jadwal_mengajar/10/1"
            )
            == 10
        )

    def test_relative_href(self):
        assert current_offset("/akademik/dsn_jadwal_dosen/view_jadwal_mengajar/20/1") == 20


LIST_PAYLOAD = [
    {"dosenId": "16764", "dosenNama": "Matin Nuhamunada, S.Si., M.Sc."},
    {"dosenId": "12345", "dosenNama": "Luthfi Nurhidayat, S.Si., M.Sc."},
]


class TestFindDosen:
    def test_matches_with_titles_and_punctuation(self):
        assert find_dosen(LIST_PAYLOAD, "Luthfi Nurhidayat") == "12345"

    def test_case_insensitive(self):
        assert find_dosen(LIST_PAYLOAD, "MATIN NUHAMUNADA") == "16764"

    def test_full_input_matches(self):
        assert find_dosen(LIST_PAYLOAD, "Matin Nuhamunada, S.Si., M.Sc.") == "16764"

    def test_unknown_returns_none(self):
        assert find_dosen(LIST_PAYLOAD, "Jane Doe") is None

    def test_not_a_list(self):
        assert find_dosen({"error": "x"}, "Matin") is None

    def test_falls_back_to_other_keys(self):
        assert find_dosen([{"label": "Jane Doe", "id": "9"}], "Jane Doe") == "9"


class TestBestMatch:
    def test_exact_substring_fast_path(self):
        item = best_match(LIST_PAYLOAD, "Matin Nuhamunada")
        assert item["dosenId"] == "16764"

    def test_title_prefix_diff_fuzzy(self):
        payload = [{"dosenId": "55", "dosenNama": "Luthfi Nurhidayat, S.Si., M.Sc."}]
        assert best_match(payload, "Dr. Luthfi Nurhidayat, S.Si., M.Sc.")["dosenId"] == "55"

    def test_extra_credential_fuzzy(self):
        payload = [{"dosenId": "66", "dosenNama": "Matin Nuhamunada, S.Si., M.Sc."}]
        assert best_match(payload, "Matin Nuhamunada, S.Si., M.Sc., Ph.D.")["dosenId"] == "66"

    def test_missing_credential_fuzzy(self):
        payload = [{"dosenId": "77", "dosenNama": "Eko Agus Suyono, S.Si., M.App.Sc."}]
        assert best_match(payload, "Prof. Dr. Eko Agus Suyono, M.App.Sc.")["dosenId"] == "77"

    def test_initial_vs_full_middle_name_fuzzy(self):
        payload = [{"dosenId": "88", "dosenNama": "Ganies Riza Aristya, S.Si., M.Sc., Ph.D."}]
        assert best_match(payload, "Ganies Riza A., S.Si., M.Sc., Ph.D.")["dosenId"] == "88"

    def test_dra_vs_dr_fuzzy(self):
        payload = [{"dosenId": "99", "dosenNama": "Rarastoeti Pratiwi, M.Sc., Ph.D."}]
        assert best_match(payload, "Prof. Dra. Rarastoeti Pratiwi, M.Sc., Ph.D.")["dosenId"] == "99"

    def test_unknown_returns_none(self):
        payload = [{"dosenId": "1", "dosenNama": "Someone Else, S.Si."}]
        assert best_match(payload, "Matin Nuhamunada") is None

    def test_empty_lecturer(self):
        assert best_match(LIST_PAYLOAD, "") is None

    def test_not_a_list(self):
        assert best_match({"error": "x"}, "Matin") is None


class TestTermCandidates:
    def test_plain_name(self):
        assert term_candidates("Matin Nuhamunada") == ["Matin Nuhamunada", "Matin"]

    def test_titled_name_skips_titles(self):
        assert term_candidates("Prof. Dr. Eko Agus Suyono, M.App.Sc.") == [
            "Eko Agus",
            "Eko",
        ]

    def test_title_fragments_skipped(self):
        assert term_candidates("Dr. rer. nat. Abdul Rahman Siregar, S.Si., M.Biotech.") == [
            "Abdul Rahman",
            "Abdul",
        ]

    def test_titled_name_with_initial_skips_two_word(self):
        assert term_candidates("Prof. Dr. Budi S. Daryono, M.Agr.Sc.") == ["Budi"]

    def test_single_given_name(self):
        assert term_candidates("Sukirno, S.Si., M.Sc., Ph.D.") == ["Sukirno"]

    def test_glued_title_adds_fallback(self):
        assert term_candidates("Dr.Utaminingsih S.Si., M.Sc.") == [
            "Dr.Utaminingsih",
            "Utaminingsih",
        ]

    def test_glued_prof(self):
        assert term_candidates("Prof.Rina Sri Kasiamdari, S.Si., Ph.D.") == [
            "Prof.Rina",
            "Rina",
        ]

    def test_empty(self):
        assert term_candidates("") == []


class TestCanonicalName:
    def test_returns_server_name(self):
        assert canonical_name(LIST_PAYLOAD, "luthfi nurhidayat") == "Luthfi Nurhidayat, S.Si., M.Sc."

    def test_unknown_returns_none(self):
        assert canonical_name(LIST_PAYLOAD, "Nobody") is None


class TestSlugify:
    def test_simple_name(self):
        assert slugify("Matin Nuhamunada") == "matin_nuhamunada"

    def test_titled_name(self):
        assert slugify("Luthfi Nurhidayat, S.Si., M.Sc.") == "luthfi_nurhidayat_s_si_m_sc"

    def test_collapses_runs_and_trim(self):
        assert slugify(" Dr. Eko Agus Suyono   ") == "dr_eko_agus_suyono"

    def test_empty_falls_back(self):
        assert slugify("") == "lecturer"